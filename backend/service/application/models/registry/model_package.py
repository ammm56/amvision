"""生成独立模型包，检查目标冲突并登记新资源。"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import uuid4

from backend.contracts.deployments.model_package import PackageFile, PortableBuild, PortableModel, PortableVersion, safe_package_path
from backend.contracts.models.model_package import ModelPackage, ModelPackageExportOptions, ModelPackageImportOptions
from backend.service.application.deployments.package_import import content_hash
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.models.registry.model_service import SqlAlchemyModelService
from backend.service.domain.files.model_file import ModelFile
from backend.service.domain.models.model_records import Model, ModelBuild, ModelVersion
from backend.service.infrastructure.object_store.model_package_archive import file_digest
from backend.service.infrastructure.persistence.model_transfer_repository import ImportedModelArtifactRecord, transfer_now
from backend.version import BACKEND_VERSION

_VERSION_FIELDS = frozenset({"category_names", "input_size", "model_input_spec", "num_classes", "model_scale", "pose_spec", "kpt_shape"})
_BUILD_FIELDS = frozenset({"model_input_spec", "input_tensor", "input_shape_mode", "optimization_profile_count", "optimization_profiles", "tensorrt_version", "platform"})
_CHECKPOINT_SUFFIXES = (".pt", ".pth")
_BUILD_SUFFIXES = {"onnx": ".onnx", "onnx-optimized": ".onnx", "openvino-ir": ".xml", "tensorrt-engine": ".engine", "rknn": ".rknn"}


def compile_model_package(unit, storage, project_id: str, options: ModelPackageExportOptions, progress) -> tuple[ModelPackage, dict[str, Path]]:
    """仅打包选择的模型文件和可移植契约。"""
    version = unit.models.get_model_version(options.model_version_id)
    model = unit.models.get_model(version.model_id) if version else None
    if not version or not model or model.project_id != project_id:
        raise ResourceNotFoundError("找不到当前项目的模型版本")
    files: list[PackageFile] = []
    sources: dict[str, Path] = {}

    def add_file(owner: str, relative: str, path: Path, file_type: str) -> None:
        """只接受受控 ObjectStore 下存在的文件。"""
        resolved = storage.resolve_deletion_path(path.relative_to(storage.root_dir).as_posix())
        if not resolved.is_file():
            raise InvalidRequestError(f"模型文件缺失：{path.name}")
        key = f"file-{len(files) + 1}"
        digest, size = file_digest(resolved, progress)
        files.append(PackageFile(key=key, owner=owner, path=relative, logical_name=path.name, file_type=file_type, sha256=digest, byte_size=size))
        sources[key] = resolved

    version_files = unit.model_files.list_model_files(model_version_id=version.model_version_id)
    weights = [item for item in version_files if item.storage_uri.lower().endswith(_CHECKPOINT_SUFFIXES)]
    if options.include_checkpoint:
        if not weights:
            raise InvalidRequestError("当前版本没有原始权重")
        for item in weights:
            path = storage.resolve(item.storage_uri)
            add_file("version", path.name, path, item.file_type)
    for item in version_files:
        if item.file_type.endswith("labels"):
            path = storage.resolve(item.storage_uri)
            add_file("version", path.name, path, item.file_type)

    builds = []
    for index, build_id in enumerate(options.build_ids):
        build = unit.models.get_model_build(build_id)
        if not build or build.source_model_version_id != version.model_version_id or build.model_id != model.model_id:
            raise InvalidRequestError("所选构建产物不属于来源模型版本")
        registered = unit.model_files.list_model_files(model_build_id=build_id)
        for item in registered:
            path = storage.resolve(item.storage_uri)
            add_file("build", f"{index}/{path.name}", path, item.file_type)
        if build.build_format == "openvino-ir":
            # 本地转换只将 XML 登记为 ModelFile；同名 BIN 由转换元数据指向。
            keys = {storage.resolve(item.storage_uri) for item in registered}
            for primary in sorted(path for path in keys if path.suffix.lower() == ".xml"):
                weights = primary.with_suffix(".bin")
                stored_uri = build.metadata.get("weights_object_uri")
                if weights not in keys and isinstance(stored_uri, str) and storage.resolve(stored_uri) == weights:
                    add_file("build", f"{index}/{weights.name}", weights, "openvino-bin")
        builds.append(PortableBuild(
            model_build_id=build_id, build_format=build.build_format, runtime_backend=build.runtime_backend,
            runtime_precision=build.runtime_precision, metadata=_fields(build.metadata, _BUILD_FIELDS),
            provenance={"conversion_task_id": build.conversion_task_id},
        ))
    display_name = model.metadata.get("display_name")
    manifest = ModelPackage(
        package_id=f"model-package-{uuid4().hex}", source_version=BACKEND_VERSION, created_at=transfer_now(),
        model=PortableModel(
            model_id=model.model_id, model_name=display_name.strip() if isinstance(display_name, str) and display_name.strip() else model.model_name, model_type=model.model_type,
            task_type=model.task_type, model_scale=model.model_scale,
        ),
        model_version=PortableVersion(
            model_version_id=version.model_version_id, metadata=_fields(version.metadata, _VERSION_FIELDS),
            provenance={
                "source_kind": version.source_kind, "training_task_id": version.training_task_id,
                "dataset_version_id": version.dataset_version_id, "parent_version_id": version.parent_version_id,
                "source_version_label": f"v{version.version_number}" if version.version_number else None,
            },
        ),
        builds=builds, files=files,
    )
    return manifest, sources


def verify_model_package_files(package: ModelPackage, files: dict[str, Path]) -> None:
    """检查权重文件组、后端和 ONNX 外部文件引用，不执行模型。"""
    categories = _categories(package.model_version.metadata)
    if not categories or len(categories) != len(set(categories)):
        raise InvalidRequestError("模型包缺少有效的类别顺序")
    for item in package.files:
        if item.owner != "version":
            continue
        if item.path.lower().endswith(_CHECKPOINT_SUFFIXES):
            import torch

            try:
                value = torch.load(files[item.key], map_location="meta", weights_only=True, mmap=True)
            except Exception as error:
                raise InvalidRequestError("模型包权重无法按纯权重格式读取") from error
            if not isinstance(value, dict):
                raise InvalidRequestError("模型包权重必须是字典格式")
        elif item.file_type.endswith("labels"):
            labels = [line.strip() for line in files[item.key].read_text(encoding="utf-8").splitlines() if line.strip()]
            if labels != categories:
                raise InvalidRequestError("标签文件与模型包的类别顺序不一致")
        else:
            raise InvalidRequestError("模型包包含不支持的版本文件")
    for index, build in enumerate(package.builds):
        candidates = [item for item in package.files if item.owner == "build" and item.path.startswith(f"{index}/")]
        registered = {item.path for item in candidates}
        suffix = _BUILD_SUFFIXES[build.build_format]
        primary = [item for item in candidates if item.path.lower().endswith(suffix)]
        if len(primary) != 1:
            raise InvalidRequestError("每组构建产物必须包含一个主文件")
        main = primary[0]
        if suffix == ".xml" and str(PurePosixPath(main.path).with_suffix(".bin")) not in registered:
            raise InvalidRequestError("OpenVINO 产物缺少同名 BIN 文件")
        if suffix == ".onnx":
            import onnx
            from onnx.external_data_helper import _get_all_tensors

            graph = onnx.load(str(files[main.key]), load_external_data=False)
            for tensor in _get_all_tensors(graph):
                if tensor.data_location != onnx.TensorProto.EXTERNAL:
                    continue
                location = next((entry.value for entry in tensor.external_data if entry.key == "location"), "")
                relative = PurePosixPath(main.path).parent / safe_package_path(location)
                if str(relative) not in registered:
                    raise InvalidRequestError("ONNX 引用了模型包外的文件")


def plan_model_package_import(unit, factory, package: ModelPackage, project_id: str, options: ModelPackageImportOptions, mapping: dict | None = None) -> dict:
    """同序类别才可追加，所有文件使用新的本地身份。"""
    registry = SqlAlchemyModelService(session_factory=factory)
    for build in package.builds:
        registry._validate_build_runtime_backend(build_format=build.build_format, runtime_backend=build.runtime_backend)
        registry._validate_build_runtime_precision(build_format=build.build_format, runtime_precision=build.runtime_precision)
    source = package.model
    name = (options.model_name or source.model_name).strip()
    categories = _categories(package.model_version.metadata)
    mapping = mapping or {
        "model": f"model-{uuid4().hex}", "version": f"model-version-{uuid4().hex}",
        "builds": [f"model-build-{uuid4().hex}" for _ in package.builds],
    }
    issues: list[dict] = []
    existing = None
    if options.target_model_id:
        existing = unit.models.get_model(options.target_model_id)
        if not existing or existing.project_id != project_id:
            raise ResourceNotFoundError("找不到当前项目的目标模型")
        name = existing.model_name
        if (existing.model_type, existing.task_type, existing.model_scale) != (source.model_type, source.task_type, source.model_scale):
            issues.append({"code": "target_incompatible", "reason": "目标模型的架构、任务或规格不同"})
        for version in unit.models.list_model_versions(existing.model_id):
            current = _categories(version.metadata)
            if current != categories:
                issues.append({"code": "category_order", "reason": "现有类别索引与模型包不一致",
                               "expected": current, "incoming": categories})
                break
    elif not name or len(name) > 128:
        issues.append({"code": "name_required", "reason": "请输入 1–128 字符的模型名称"})
    elif unit.models.find_model(project_id=project_id, scope_kind="project", model_name=name, model_scale=source.model_scale, task_type=source.task_type):
        issues.append({"code": "name_conflict", "reason": "当前项目已有同名同规格模型，请追加版本或改名"})
    return {"name": name, "mapping": mapping, "target_model_id": existing.model_id if existing else None, "issues": issues, "can_import": not issues}


def register_model_package(unit, package: ModelPackage, project_id: str, plan: dict, options: ModelPackageImportOptions, prefixes: dict[str, str]) -> dict:
    """在同一事务登记版本与文件，源任务和源版本只作为可追溯信息。"""
    ids = plan["mapping"]
    model_id = plan["target_model_id"] or ids["model"]
    version_id = ids["version"]
    if not plan["target_model_id"]:
        unit.models.save_model(Model(
            model_id=model_id, project_id=project_id, model_name=plan["name"],
            model_type=package.model.model_type, task_type=package.model.task_type, model_scale=package.model.model_scale,
        ))
        unit.flush()
    groups: dict[str, list[tuple[PackageFile, str, str]]] = {key: [] for key in prefixes}
    for item in package.files:
        owner, name = item.path.split("/", 1) if item.owner == "build" else ("version", item.path)
        groups[owner].append((item, f"model-file-{uuid4().hex}", name))
    unit.models.save_model_version(ModelVersion(
        model_version_id=version_id, model_id=model_id, source_kind="model-package-import",
        file_ids=tuple(file_id for _, file_id, _ in groups["version"]),
        metadata={**_fields(package.model_version.metadata, _VERSION_FIELDS),
                  "description": options.description,
                  "import_provenance": {
                      **_fields(package.model_version.provenance, frozenset({"source_kind", "dataset_version_id", "training_task_id", "parent_version_id", "source_version_label"})),
                      "package_id": package.package_id, "source_version_id": package.model_version.model_version_id,
                  }},
    ))
    unit.flush()
    for index, build in enumerate(package.builds):
        unit.models.save_model_build(ModelBuild(
            model_build_id=ids["builds"][index], model_id=model_id, source_model_version_id=version_id,
            build_format=build.build_format, runtime_backend=build.runtime_backend, runtime_precision=build.runtime_precision,
            file_ids=tuple(file_id for _, file_id, _ in groups[str(index)]),
            metadata={**_fields(build.metadata, _BUILD_FIELDS), "import_provenance": {
                "conversion_task_id": build.provenance.get("conversion_task_id"), "source_build_id": build.model_build_id,
            }},
        ))
    unit.flush()
    for owner, items in groups.items():
        build_id = None if owner == "version" else ids["builds"][int(owner)]
        unit.session.add(ImportedModelArtifactRecord(
            artifact_id=f"imported-{uuid4().hex}", project_id=project_id,
            model_version_id=None if build_id else version_id, model_build_id=build_id,
            object_prefix=prefixes[owner], fingerprint=content_hash([item.sha256 for item, _, _ in items]),
            provenance_json={"package_id": package.package_id},
        ))
        for item, file_id, name in items:
            unit.model_files.save_model_file(ModelFile(
                file_id=file_id, project_id=project_id, model_id=model_id,
                model_version_id=None if build_id else version_id, model_build_id=build_id,
                file_type=item.file_type, logical_name=item.logical_name,
                storage_uri=f"{prefixes[owner]}/files/{name}",
                metadata={"sha256": item.sha256, "byte_size": item.byte_size},
            ))
    return {"model_id": model_id, "model_version_id": version_id, "model_build_ids": ids["builds"]}


def _categories(metadata: dict[str, object]) -> list[str]:
    """只承认有序、非空的字符串类别。"""
    names = metadata.get("category_names")
    return names if isinstance(names, list) and all(isinstance(name, str) and name.strip() for name in names) else []


def _fields(metadata: dict[str, object], fields: frozenset[str]) -> dict[str, object]:
    """保留约定的模型输入和运行字段，丢弃任务和部署目录。"""
    return {key: metadata[key] for key in fields if key in metadata}
