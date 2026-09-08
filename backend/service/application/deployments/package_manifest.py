"""从实例固定快照编译单模型文件集，不递归打包任务目录。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4
from backend.version import BACKEND_VERSION

from backend.contracts.deployments.model_package import ModelDeploymentPackage, PackageFile, safe_package_path
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.domain.deployments.deployment_runtime_configuration import serialize_deployment_runtime_configuration
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.model_package_archive import file_digest
from backend.service.infrastructure.persistence.model_transfer_repository import transfer_now


def compile_deployment_package(factory, storage, deployment_id: str, project_id: str, progress=None) -> tuple[ModelDeploymentPackage, dict[str, Path]]:
    """读取实际固定目标；缺失、错属或损坏的文件立即失败。"""
    unit = SqlAlchemyUnitOfWork(factory.create_session())
    try:
        deployment = unit.deployments.get_deployment_instance(deployment_id)
        if deployment is None or deployment.project_id != project_id:
            raise ResourceNotFoundError("当前项目中没有该部署实例")
        model = unit.models.get_model(deployment.model_id)
        version = unit.models.get_model_version(deployment.model_version_id)
        build = unit.models.get_model_build(deployment.model_build_id) if deployment.model_build_id else None
        snap = deployment.metadata.get("runtime_target_snapshot", {})
        if not model or not version or (deployment.model_build_id and not build):
            raise InvalidRequestError("部署模型登记不完整")
        for key, expected in {"model_id": model.model_id, "model_version_id": version.model_version_id, "model_build_id": deployment.model_build_id, "project_id": project_id, "model_type": model.model_type, "task_type": model.task_type, "runtime_backend": deployment.runtime_backend}.items():
            if snap.get(key) != expected:
                raise InvalidRequestError("部署快照与模型登记不一致", details={"field": key})
        sources: dict[str, Path] = {}
        files: list[PackageFile] = []
        file_references = {}

        def add_file(key: str, owner: str, path: Path, file_type: str, relative: str | None = None) -> str:
            """登记一个受管普通文件，相同文件引用共用 key。"""
            resolved = storage.resolve_deletion_path(str(path))
            if not resolved.is_file():
                raise InvalidRequestError("部署所需文件不存在", details={"file": path.name})
            for existing_key, existing_path in sources.items():
                if existing_path == resolved:
                    return existing_key
            digest, size = file_digest(resolved, progress)
            files.append(PackageFile(key=key, owner=owner, path=safe_package_path(relative or path.name), logical_name=path.name, file_type=file_type, sha256=digest, byte_size=size))
            sources[key] = resolved
            return key

        for slot, id_key, uri_key in (("runtime_file", "runtime_artifact_file_id", "runtime_artifact_storage_uri"), ("checkpoint_file", "checkpoint_file_id", "checkpoint_storage_uri")):
            fid = snap.get(id_key)
            if fid is None:
                if slot == "runtime_file":
                    raise InvalidRequestError("部署缺少运行文件")
                file_references[slot] = None
                continue
            record = unit.model_files.get_model_file(fid)
            if record is None or record.storage_uri != snap.get(uri_key) or record.model_id != model.model_id:
                raise InvalidRequestError("部署文件引用与登记不一致", details={"file_id": fid})
            owner = "build" if slot == "runtime_file" and build else "version"
            file_references[slot] = add_file(fid, owner, storage.resolve(record.storage_uri), record.file_type)
        labels_uri = snap.get("labels_storage_uri")
        file_references["labels_file"] = None
        if labels_uri:
            path = storage.resolve(labels_uri)
            registered = next((item for item in unit.model_files.list_model_files(model_version_id=version.model_version_id) if item.storage_uri == labels_uri), None)
            file_references["labels_file"] = add_file("labels", "version", path, registered.file_type if registered else "labels")
            labels = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if labels != snap.get("labels"):
                raise InvalidRequestError("标签文件与固定部署类别不一致")
        runtime_path = sources[file_references["runtime_file"]]
        if build and build.build_format == "openvino-ir":
            add_file("openvino-weights", "build", runtime_path.with_suffix(".bin"), "openvino-weights")
        if build and build.build_format in {"onnx", "onnx-optimized"}:
            import onnx
            from onnx.external_data_helper import _get_all_tensors
            graph = onnx.load(str(runtime_path), load_external_data=False)
            for tensor in _get_all_tensors(graph):
                for entry in tensor.external_data:
                    if entry.key == "location":
                        relative = safe_package_path(entry.value)
                        add_file(f"external-{len(files)}", "build", runtime_path.parent / relative, "onnx-external-data", relative)
        configuration = serialize_deployment_runtime_configuration(deployment.runtime_configuration)
        inference = {key: snap.get(key) for key in ("runtime_precision", "input_size", "model_input_spec", "labels", "model_config", "model_build_metadata")}
        inference.update(file_references)
        metadata = {"category_names": list(snap["labels"]), "input_size": snap["input_size"]}
        if snap.get("model_input_spec"):
            metadata["model_input_spec"] = snap["model_input_spec"]
        metadata.update(snap.get("model_config") or {})
        metadata.update({"category_names": list(snap["labels"]), "input_size": snap["input_size"]})
        if snap.get("model_input_spec"):
            metadata["model_input_spec"] = snap["model_input_spec"]
        manifest = ModelDeploymentPackage.model_validate({
            "package_id": f"deployment-package-{uuid4().hex}", "source_version": BACKEND_VERSION, "created_at": transfer_now(),
            "deployment": {"deployment_instance_id": deployment_id, "display_name": deployment.display_name, "runtime_backend": deployment.runtime_backend, "device_name": deployment.device_name, "runtime_profile_id": deployment.runtime_profile_id, "runtime_configuration": configuration},
            "model": {key: getattr(model, key) for key in ("model_id", "model_name", "model_type", "task_type", "model_scale")},
            "model_version": {"model_version_id": version.model_version_id, "metadata": metadata, "provenance": {"source_kind": version.source_kind, "training_task_id": version.training_task_id, "dataset_version_id": version.dataset_version_id}},
            "model_build": {"model_build_id": build.model_build_id, "build_format": build.build_format, "runtime_backend": build.runtime_backend, "runtime_precision": build.runtime_precision, "runtime_profile_id": build.runtime_profile_id, "metadata": snap.get("model_build_metadata") or {}, "provenance": {"conversion_task_id": build.conversion_task_id}} if build else None,
            "inference": inference, "files": [f.model_dump() for f in files],
        })
        return manifest, sources
    finally:
        unit.close()
