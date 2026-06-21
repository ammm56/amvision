"""YOLO detection 训练数据集解析工具。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.datasets.formats import (
    require_supported_dataset_export_format,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


class YoloDetectionDatasetExportRequest(Protocol):
    """描述解析 detection 训练 DatasetExport 所需的请求字段。"""

    project_id: str
    dataset_export_id: str | None
    dataset_export_manifest_key: str | None


def resolve_yolo_detection_training_dataset_export(
    *,
    session_factory: SessionFactory,
    request: YoloDetectionDatasetExportRequest,
    model_name: str,
    model_label: str,
) -> DatasetExport:
    """根据训练请求解析可用于当前模型的 DatasetExport。

    - session_factory：数据库 session factory。
    - request：包含 project_id、dataset_export_id 和 dataset_export_manifest_key 的请求对象。
    - model_name：当前模型类型，例如 yolov8、yolo11、yolo26。
    - model_label：错误信息中展示的模型名称。
    """

    export_by_id = None
    if request.dataset_export_id is not None:
        export_by_id = _get_yolo_detection_dataset_export(
            session_factory=session_factory,
            dataset_export_id=request.dataset_export_id,
        )

    export_by_manifest = None
    if request.dataset_export_manifest_key is not None:
        export_by_manifest = _get_yolo_detection_dataset_export_by_manifest(
            session_factory=session_factory,
            manifest_object_key=request.dataset_export_manifest_key,
        )

    dataset_export = export_by_id or export_by_manifest
    if dataset_export is None:
        raise ResourceNotFoundError("找不到可用于训练的 DatasetExport")
    if (
        export_by_id is not None
        and export_by_manifest is not None
        and export_by_id.dataset_export_id != export_by_manifest.dataset_export_id
    ):
        raise InvalidRequestError(
            "dataset_export_id 与 dataset_export_manifest_key 不属于同一个 DatasetExport",
            details={
                "dataset_export_id": export_by_id.dataset_export_id,
                "manifest_object_key": request.dataset_export_manifest_key,
            },
        )
    if dataset_export.project_id != request.project_id:
        raise InvalidRequestError(
            "请求中的 project_id 与 DatasetExport 不一致",
            details={"dataset_export_id": dataset_export.dataset_export_id},
        )
    if dataset_export.status != "completed":
        raise InvalidRequestError(
            "当前 DatasetExport 尚未完成，不能用于训练",
            details={
                "dataset_export_id": dataset_export.dataset_export_id,
                "status": dataset_export.status,
            },
        )
    require_supported_dataset_export_format(
        model_type=model_name,
        task_type=DETECTION_TASK_TYPE,
        format_id=dataset_export.format_id,
        dataset_export_id=dataset_export.dataset_export_id,
        unsupported_message=(
            f"当前 {model_label} detection 训练只接受当前模型支持的 detection 导出格式"
        ),
    )
    if (
        dataset_export.manifest_object_key is None
        or not dataset_export.manifest_object_key.strip()
    ):
        raise InvalidRequestError(
            "当前 DatasetExport 缺少 manifest_object_key，不能用于训练",
            details={"dataset_export_id": dataset_export.dataset_export_id},
        )
    return dataset_export


def _get_yolo_detection_dataset_export(
    *,
    session_factory: SessionFactory,
    dataset_export_id: str,
) -> DatasetExport:
    """按 id 读取一个 DatasetExport。"""

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        dataset_export = unit_of_work.dataset_exports.get_dataset_export(
            dataset_export_id
        )
    finally:
        unit_of_work.close()
    if dataset_export is None:
        raise ResourceNotFoundError(
            "找不到指定的 DatasetExport",
            details={"dataset_export_id": dataset_export_id},
        )
    return dataset_export


def _get_yolo_detection_dataset_export_by_manifest(
    *,
    session_factory: SessionFactory,
    manifest_object_key: str,
) -> DatasetExport:
    """按 manifest object key 读取一个 DatasetExport。"""

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        dataset_export = (
            unit_of_work.dataset_exports.get_dataset_export_by_manifest_object_key(
                manifest_object_key
            )
        )
    finally:
        unit_of_work.close()
    if dataset_export is None:
        raise ResourceNotFoundError(
            "找不到指定 manifest_object_key 对应的 DatasetExport",
            details={"manifest_object_key": manifest_object_key},
        )
    return dataset_export
