"""训练提交前检查模型登记、数据导出及初始化文件。"""

from hashlib import file_digest
from string import hexdigits
from typing import Literal, NotRequired, TypedDict

from backend.service.application.datasets.formats.export_support import (
    build_supported_dataset_export_formats_by_task_and_model_type,
)
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError, ServiceError
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_records import PLATFORM_BASE_MODEL_SCOPE, PROJECT_MODEL_SCOPE
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.filesystem.shared_files import open_shared_read
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class TrainingSubmissionCheck(TypedDict):
    """向导预检的单项结果及可操作的失败信息。"""

    check: Literal["dataset_export", "initialization", "output_model", "environment"]
    status: Literal["passed", "failed", "skipped", "deferred"]
    message: NotRequired[str]
    missing_files: NotRequired[list[str]]


def check_output_model_identity(
    *, session_factory: SessionFactory, project_id: str, task_type: str,
    model_type: str, model_scale: str, output_model_name: str,
) -> None:
    """核对项目内的输出名称、规格与模型系列，允许同系列追加版本。"""
    with session_factory.create_session() as session:
        unit = SqlAlchemyUnitOfWork(session)
        model = unit.models.find_model(
            project_id=project_id, scope_kind=PROJECT_MODEL_SCOPE, model_name=output_model_name.strip(),
            model_scale=model_scale, task_type=task_type, allow_display_name=True,
        )
        if model is not None and model.model_type != model_type:
            raise InvalidRequestError(
                "同名同规格模型的系列不匹配，请选择其他输出模型名称",
                details={"model_id": model.model_id, "existing_model_type": model.model_type,
                         "requested_model_type": model_type},
            )


def inspect_training_submission(
    *, session_factory: SessionFactory, storage: LocalDatasetStorage, project_id: str,
    task_type: str, model_type: str, model_scale: str, dataset_export_id: str | None,
    manifest_key: str | None, warm_start_version_id: str | None, output_model_name: str,
) -> dict[str, object]:
    """独立检查各项资源，保留预检客户端所用的错误码及导出摘要。"""

    checks: list[TrainingSubmissionCheck] = []
    failures: list[ServiceError] = []
    summary: dict[str, object] = {}
    try:
        check_output_model_identity(
            session_factory=session_factory, project_id=project_id, task_type=task_type,
            model_type=model_type, model_scale=model_scale, output_model_name=output_model_name,
        )
    except InvalidRequestError as error:
        failures.append(error)
        checks.append({"check": "output_model", "status": "failed", "message": error.message})
    else:
        checks.append({"check": "output_model", "status": "passed"})
    with session_factory.create_session() as session:
        unit = SqlAlchemyUnitOfWork(session)
        try:
            summary = _inspect_training_export(
                unit, storage, project_id=project_id, task_type=task_type, model_type=model_type,
                dataset_export_id=dataset_export_id, manifest_key=manifest_key,
            )
        except (InvalidRequestError, ResourceNotFoundError) as error:
            failures.append(error)
            result: TrainingSubmissionCheck = {"check": "dataset_export", "status": "failed", "message": error.message}
            if isinstance(missing_files := error.details.get("missing_files"), list):
                result["missing_files"] = missing_files
            checks.append(result)
        else:
            checks.append({"check": "dataset_export", "status": "passed"})

        try:
            _inspect_initialization(
                unit, storage, project_id=project_id, task_type=task_type, model_type=model_type,
                model_scale=model_scale, version_id=warm_start_version_id,
            )
        except (InvalidRequestError, ResourceNotFoundError) as error:
            failures.append(error)
            checks.append({"check": "initialization", "status": "failed", "message": error.message})
        else:
            checks.append({"check": "initialization", "status": "passed" if warm_start_version_id else "skipped"})
    checks.append({"check": "environment", "status": "deferred"})
    if failures:
        first = failures[0]
        first.details["checks"] = checks
        raise first
    return {**summary, "checks": checks}


def _inspect_training_export(
    unit: SqlAlchemyUnitOfWork, storage: LocalDatasetStorage, *, project_id: str, task_type: str,
    model_type: str, dataset_export_id: str | None, manifest_key: str | None,
) -> dict[str, object]:
    """核对当前项目的导出记录和清单中声明的必需资源。"""

    export = (unit.dataset_exports.get_dataset_export(dataset_export_id) if dataset_export_id else
              unit.dataset_exports.get_dataset_export_by_manifest_object_key(manifest_key) if manifest_key else None)
    if export is None or export.project_id != project_id:
        raise ResourceNotFoundError("找不到当前项目的训练数据集导出")
    accepted_formats = build_supported_dataset_export_formats_by_task_and_model_type().get(task_type, {}).get(model_type, [])
    if export.task_type != task_type or export.format_id not in accepted_formats:
        raise InvalidRequestError("导出格式或任务类型不适用于所选模型", details={"format_id": export.format_id})
    if export.status != "completed" or export.metadata.get("files_cleaned_at"):
        raise InvalidRequestError("所选数据集导出尚未完成或文件已清理")
    key = export.manifest_object_key
    if not key or (manifest_key and key != manifest_key) or not storage.resolve(key).is_file():
        raise InvalidRequestError("所选导出的清单文件不存在或已变化，请重新选择数据集导出")
    counts = export.metadata.get("split_counts")
    if (export.split_names and not {"train", "val"}.issubset(export.split_names)) or (
        isinstance(counts, dict) and any(counts.get(split) == 0 for split in ("train", "val"))
    ):
        raise InvalidRequestError("训练集和验证集都需要包含样本")
    _inspect_export_manifest(storage, export, key)
    return {
        "dataset_export_id": export.dataset_export_id,
        "dataset_version_id": export.dataset_version_id,
        "format_id": export.format_id,
        "split_counts": counts if isinstance(counts, dict) else {},
    }


def _inspect_export_manifest(storage: LocalDatasetStorage, export: DatasetExport, key: str) -> None:
    """确认清单可读，并检查训练和验证划分直接声明的文件、目录。"""

    try:
        manifest = storage.read_json(key)
    except (ValueError, OSError) as error:
        raise InvalidRequestError("无法读取训练数据导出清单，请重新导出") from error
    if not isinstance(manifest, dict) or any(
        field in manifest and manifest[field] != expected
        for field, expected in (("dataset_version_id", export.dataset_version_id), ("format_id", export.format_id))
    ):
        raise InvalidRequestError("导出清单与选定的数据版本或格式不一致")
    splits = manifest.get("splits")
    if not isinstance(splits, list):
        raise InvalidRequestError("导出清单缺少训练和验证划分")
    required_splits = [split for split in splits if isinstance(split, dict) and split.get("name") in ("train", "val")]
    if {split["name"] for split in required_splits} != {"train", "val"} or any(
        split.get("sample_count") == 0 for split in required_splits
    ):
        raise InvalidRequestError("训练集和验证集都需要包含样本")
    missing = set()
    export_root = storage.resolve(export.export_path).resolve() if export.export_path else storage.resolve(key).parent.resolve()
    fields = ("image_root", "label_root", "annotation_root", "class_mask_root", "object_mask_root", "annotation_file", "image_set_file")
    for split in required_splits:
        for field in fields:
            value = split.get(field)
            if not isinstance(value, str) or not value:
                continue
            path = storage.resolve(value).resolve()
            if not path.is_relative_to(export_root):
                raise InvalidRequestError("导出清单中的文件路径超出了所选导出的范围")
            exists = path.is_dir() if field.endswith("_root") else path.is_file()
            if not exists:
                missing.add(path.relative_to(export_root).as_posix())
    if missing:
        raise InvalidRequestError(
            "训练数据导出缺少必需的文件或目录，请重新导出",
            details={"missing_files": sorted(missing)},
        )


def _inspect_initialization(
    unit: SqlAlchemyUnitOfWork, storage: LocalDatasetStorage, *, project_id: str, task_type: str,
    model_type: str, model_scale: str, version_id: str | None,
) -> None:
    """核对初始化版本和文件；存在登记摘要时比较本地 SHA-256。"""

    if not version_id:
        return
    version = unit.models.get_model_version(version_id)
    source = unit.models.get_model(version.model_id) if version else None
    if source is None or (source.scope_kind != PLATFORM_BASE_MODEL_SCOPE and source.project_id != project_id):
        raise ResourceNotFoundError("找不到指定的初始化权重")
    if (source.task_type, source.model_type, source.model_scale) != (task_type, model_type, model_scale):
        raise InvalidRequestError("初始化权重与所选模型的任务、系列或规格不匹配")
    files = unit.model_files.list_model_files(model_version_id=version_id)
    checkpoint = next((item for item in files if item.file_type.endswith("checkpoint") and "://" not in item.storage_uri), None)
    if not checkpoint:
        raise InvalidRequestError("初始化权重文件不可用")
    filename = storage.resolve(checkpoint.storage_uri)
    if not filename.is_file():
        raise InvalidRequestError("初始化权重文件不可用")
    digest = checkpoint.metadata.get("sha256")
    if isinstance(digest, str) and len(digest) == 64 and all(char in hexdigits for char in digest):
        try:
            with open_shared_read(filename) as stream:
                actual = file_digest(stream, "sha256").hexdigest()
        except OSError as error:
            raise InvalidRequestError("无法读取初始化权重文件") from error
        if actual != digest.lower():
            raise InvalidRequestError("初始化权重文件摘要与登记值不一致")
