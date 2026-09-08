"""导入计划、固定身份映射及事务内登记；不启动任何推理进程。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from uuid import uuid4

from sqlalchemy import select

from backend.contracts.deployments.model_package import ImportOptions, ModelDeploymentPackage
from backend.service.application.deployments.deployment_instance_service import _validate_runtime_configuration
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.targets.runtime_target import normalize_device_name
from backend.service.domain.deployments.deployment_instance import DeploymentInstance
from backend.service.domain.deployments.deployment_runtime_configuration import deserialize_deployment_runtime_configuration, serialize_deployment_runtime_configuration
from backend.service.domain.deployments.deployment_runtime_state import DeploymentRuntimeState
from backend.service.domain.files.model_file import ModelFile
from backend.service.domain.models.model_records import Model, ModelBuild, ModelVersion
from backend.service.infrastructure.persistence.model_transfer_repository import ImportedModelArtifactRecord, transfer_now


def content_hash(value: object) -> str:
    """规范 JSON 摘要，仅用于内容比较。"""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def owner_fingerprint(package: ModelDeploymentPackage, owner: str) -> str:
    """模型语义与文件一并比较，不能仅凭权重摘要复用。"""
    metadata = package.model_version.metadata if owner == "version" else package.model_build.metadata
    files = sorted((f.path, f.file_type, f.sha256, f.byte_size) for f in package.files if f.owner == owner)
    value = {"model_type": package.model.model_type, "task_type": package.model.task_type, "scale": package.model.model_scale, "metadata": metadata, "files": files}
    if owner == "build":
        value.update({"version": owner_fingerprint(package, "version"), "format": package.model_build.build_format, "backend": package.model_build.runtime_backend, "precision": package.model_build.runtime_precision})
    return content_hash(value)


def target_configuration(package: ModelDeploymentPackage, options: ImportOptions):
    """复用现有设备/后端配置校验，不静默套用目标默认配置。"""
    device = normalize_device_name(options.device_name or package.deployment.device_name, runtime_backend=package.deployment.runtime_backend)
    raw_configuration = options.runtime_configuration or package.deployment.runtime_configuration
    configuration = deserialize_deployment_runtime_configuration(raw_configuration)
    normalized = serialize_deployment_runtime_configuration(configuration)
    for group, fields in raw_configuration.items():
        if group not in normalized or not isinstance(fields, dict) or any(key not in normalized[group] for key in fields):
            raise InvalidRequestError("运行配置含不支持的字段", details={"field_path": group})
    if options.instance_count is not None:
        configuration = replace(configuration, execution=replace(configuration.execution, instance_count=options.instance_count))
    _validate_runtime_configuration(configuration, runtime_backend=package.deployment.runtime_backend, device_name=device, model_build_metadata=package.inference.model_build_metadata)
    return device, configuration


def plan_import(unit, package: ModelDeploymentPackage, project_id: str, options: ImportOptions, existing_mapping: dict | None = None) -> dict:
    """计算单部署固定关系的冲突和复用，生成一次分析可复用的 ID。"""
    mapping = dict(existing_mapping or {})
    original = {"model": package.model.model_id, "version": package.model_version.model_version_id}
    if package.model_build:
        original["build"] = package.model_build.model_build_id
    original["deployment"] = package.deployment.deployment_instance_id
    try:
        device, configuration = target_configuration(package, options)
    except (InvalidRequestError, TypeError, ValueError) as error:
        return {"mapping": mapping or original, "original": original, "reused": [], "issues": [{"code": "invalid_runtime_configuration", "reason": str(error), "blocking": True}], "can_import": False, "device_name": options.device_name or package.deployment.device_name, "runtime_configuration": options.runtime_configuration or package.deployment.runtime_configuration, "display_name": options.display_name or package.deployment.display_name, "total_bytes": sum(f.byte_size for f in package.files)}
    reused, conflicts = [], []
    getters = {"model": unit.models.get_model, "version": unit.models.get_model_version, "build": unit.models.get_model_build, "deployment": unit.deployments.get_deployment_instance}
    for kind, source_id in original.items():
        target_id = mapping.get(kind, source_id)
        row = getters[kind](target_id)
        if row is not None:
            can_reuse = False
            if kind == "model":
                can_reuse = row.project_id == project_id and (row.model_type, row.task_type, row.model_scale, row.model_name) == (package.model.model_type, package.model.task_type, package.model.model_scale, package.model.model_name)
            elif kind in {"version", "build"}:
                column = ImportedModelArtifactRecord.model_version_id if kind == "version" else ImportedModelArtifactRecord.model_build_id
                owned = unit.session.scalar(select(ImportedModelArtifactRecord).where(column == target_id))
                can_reuse = bool(owned and owned.project_id == project_id and owned.fingerprint == owner_fingerprint(package, kind) and row.model_id == mapping.get("model", original["model"]))
                if kind == "build":
                    can_reuse = can_reuse and row.source_model_version_id == mapping["version"]
            elif kind == "deployment":
                can_reuse = row.project_id == project_id and row.metadata.get("deployment_import_fingerprint") == content_hash({"version": owner_fingerprint(package, "version"), "build": owner_fingerprint(package, "build") if package.model_build else None, "inference": package.inference.model_dump(), "device": device, "configuration": serialize_deployment_runtime_configuration(configuration)})
                can_reuse = can_reuse and (row.model_id, row.model_version_id, row.model_build_id, row.device_name, row.display_name, serialize_deployment_runtime_configuration(row.runtime_configuration)) == (mapping["model"], mapping["version"], mapping.get("build"), device, options.display_name or package.deployment.display_name, serialize_deployment_runtime_configuration(configuration))
            if can_reuse:
                reused.append(kind)
            elif options.create_copy:
                target_id = f"{kind}-import-{uuid4().hex}"
            else:
                conflicts.append({"code": "id_conflict", "resource_kind": kind, "resource_id": source_id, "reason": "目标已有不同内容或不同归属的同 ID 资源", "blocking": True})
        mapping[kind] = target_id
    # Model 自然键不能用新 ID 绕过；兼容的模型聚合可复用。
    if "model" not in reused and not conflicts:
        same = unit.models.find_model(project_id=project_id, scope_kind="project", model_name=package.model.model_name, model_scale=package.model.model_scale, task_type=package.model.task_type)
        if same:
            if same.model_type != package.model.model_type:
                conflicts.append({"code": "model_name_conflict", "reason": "同名模型的类型不同，请先调整目标模型名称", "blocking": True})
            else:
                mapping["model"] = same.model_id
                reused.append("model")
    from importlib.util import find_spec
    from backend.service.application.runtime.deployment.runtime_capabilities import inspect_deployment_runtime_capabilities
    backend = package.deployment.runtime_backend
    module = {"pytorch": "torch", "onnxruntime": "onnxruntime", "openvino": "openvino", "tensorrt": "tensorrt", "rknn": "rknnlite"}[backend]
    if find_spec(module) is None:
        conflicts.append({"code": "runtime_unavailable", "reason": f"目标 Python 环境未安装 {module}", "blocking": True})
    elif backend in {"openvino", "tensorrt"}:
        capability = inspect_deployment_runtime_capabilities(runtime_backend=backend, device_name=device)
        if not capability["available"]:
            conflicts.append({"code": "device_unavailable", "reason": "；".join(capability["warnings"]) or f"目标设备 {device} 不可用", "blocking": True})
    return {"mapping": mapping, "original": original, "reused": reused, "issues": conflicts, "can_import": not conflicts, "device_name": device, "runtime_configuration": serialize_deployment_runtime_configuration(configuration), "display_name": options.display_name or package.deployment.display_name, "total_bytes": sum(f.byte_size for f in package.files)}


def register_import(unit, package: ModelDeploymentPackage, project_id: str, plan: dict, prefixes: dict, actor: str | None) -> str:
    """全部对象由同一个 UoW 提交，路径必须已在受管目录准备完成。"""
    if plan["issues"]:
        raise InvalidRequestError("导入存在未解决冲突", details={"issues": plan["issues"]})
    ids, reused = plan["mapping"], plan["reused"]
    if "deployment" in reused:
        return ids["deployment"]
    if "model" not in reused:
        unit.models.save_model(Model(model_id=ids["model"], project_id=project_id, model_name=package.model.model_name, model_type=package.model.model_type, task_type=package.model.task_type, model_scale=package.model.model_scale))
        unit.flush()
    file_ids = {f.key: "model-file-" + content_hash([ids[f.owner], f.key])[:40] for f in package.files}
    for owner in ("version", "build"):
        if owner in reused:
            existing_files = unit.model_files.list_model_files(**{"model_version_id" if owner == "version" else "model_build_id": ids[owner]})
            for item in package.files:
                if item.owner == owner:
                    expected_uri = f"{prefixes[owner]}/files/{item.path}"
                    existing = next((f for f in existing_files if f.storage_uri == expected_uri), None)
                    if existing is None:
                        raise InvalidRequestError("复用模型的文件登记不完整")
                    file_ids[item.key] = existing.file_id
    if "version" not in reused:
        unit.models.save_model_version(ModelVersion(model_version_id=ids["version"], model_id=ids["model"], source_kind="deployment-import", file_ids=tuple(file_ids[f.key] for f in package.files if f.owner == "version"), metadata={**package.model_version.metadata, "import_provenance": package.model_version.provenance}))
        unit.flush()
    if package.model_build and "build" not in reused:
        build = package.model_build
        unit.models.save_model_build(ModelBuild(model_build_id=ids["build"], model_id=ids["model"], source_model_version_id=ids["version"], build_format=build.build_format, runtime_backend=build.runtime_backend, runtime_precision=build.runtime_precision, runtime_profile_id=build.runtime_profile_id, file_ids=tuple(file_ids[f.key] for f in package.files if f.owner == "build"), metadata={**build.metadata, "import_provenance": build.provenance}))
        unit.flush()
    for owner in ("version", "build"):
        if owner not in ids:
            continue
        if owner not in reused:
            unit.session.add(ImportedModelArtifactRecord(artifact_id=f"imported-{uuid4().hex}", project_id=project_id, model_version_id=ids[owner] if owner == "version" else None, model_build_id=ids[owner] if owner == "build" else None, object_prefix=prefixes[owner], fingerprint=owner_fingerprint(package, owner), provenance_json={"package_id": package.package_id, "source_id": plan["original"][owner]}))
            for item in package.files:
                if item.owner == owner:
                    unit.model_files.save_model_file(ModelFile(file_id=file_ids[item.key], project_id=project_id, model_id=ids["model"], model_version_id=ids[owner] if owner == "version" else None, model_build_id=ids[owner] if owner == "build" else None, file_type=item.file_type, logical_name=item.logical_name, storage_uri=f"{prefixes[owner]}/files/{item.path}"))
    unit.flush()
    files = {f.key: f for f in package.files}
    def uri(key):
        """把包内文件引用映射为目标存储 URI。"""
        return f"{prefixes[files[key].owner]}/files/{files[key].path}" if key else None
    inf = package.inference
    runtime_file = files[inf.runtime_file]
    snapshot = {"project_id": project_id, "model_id": ids["model"], "model_type": package.model.model_type, "model_version_id": ids["version"], "model_build_id": ids.get("build"), "model_name": package.model.model_name, "model_scale": package.model.model_scale, "task_type": package.model.task_type, "source_kind": "deployment-import", "runtime_profile_id": package.deployment.runtime_profile_id, "runtime_backend": package.deployment.runtime_backend, "device_name": plan["device_name"], "runtime_precision": inf.runtime_precision, "input_size": inf.input_size, "model_input_spec": inf.model_input_spec, "labels": inf.labels, "runtime_artifact_file_id": file_ids[inf.runtime_file], "runtime_artifact_storage_uri": uri(inf.runtime_file), "runtime_artifact_file_type": runtime_file.file_type, "checkpoint_file_id": file_ids.get(inf.checkpoint_file), "checkpoint_storage_uri": uri(inf.checkpoint_file), "labels_storage_uri": uri(inf.labels_file), "model_config": inf.model_options, "model_build_metadata": inf.model_build_metadata}
    fingerprint = content_hash({"version": owner_fingerprint(package, "version"), "build": owner_fingerprint(package, "build") if package.model_build else None, "inference": inf.model_dump(), "device": plan["device_name"], "configuration": plan["runtime_configuration"]})
    now = transfer_now()
    unit.deployments.save_deployment_instance(DeploymentInstance(deployment_instance_id=ids["deployment"], project_id=project_id, model_id=ids["model"], model_version_id=ids["version"], model_build_id=ids.get("build"), runtime_profile_id=package.deployment.runtime_profile_id, runtime_backend=package.deployment.runtime_backend, device_name=plan["device_name"], runtime_configuration=deserialize_deployment_runtime_configuration(plan["runtime_configuration"]), display_name=plan["display_name"], created_at=now, updated_at=now, created_by=actor, metadata={"runtime_target_snapshot": snapshot, "deployment_import_fingerprint": fingerprint, "creation_source": "deployment-import"}))
    for mode in ("sync", "async"):
        unit.deployment_runtime_states.save_deployment_runtime_state(DeploymentRuntimeState(deployment_instance_id=ids["deployment"], runtime_mode=mode, created_at=now, updated_at=now))
    return ids["deployment"]
