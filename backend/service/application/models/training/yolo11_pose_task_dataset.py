"""YOLO11 pose 训练数据集解析工具。"""

from __future__ import annotations

from backend.service.application.datasets.formats import (
    require_supported_dataset_export_format,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import POSE_TASK_TYPE
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


def resolve_yolo11_pose_training_dataset_export(
    *,
    session_factory: SessionFactory,
    project_id: str,
    dataset_export_id: str | None,
    dataset_export_manifest_key: str | None,
    model_type: str,
) -> DatasetExport:
    """根据训练请求解析可用于 YOLO11 pose 训练的 DatasetExport。"""

    export_by_id = None
    if dataset_export_id is not None:
        export_by_id = _get_yolo11_pose_dataset_export(
            session_factory=session_factory,
            dataset_export_id=dataset_export_id,
        )

    export_by_manifest = None
    if dataset_export_manifest_key is not None:
        export_by_manifest = _get_yolo11_pose_dataset_export_by_manifest(
            session_factory=session_factory,
            manifest_object_key=dataset_export_manifest_key,
        )

    dataset_export = export_by_id or export_by_manifest
    if dataset_export is None:
        raise ResourceNotFoundError("找不到可用于 YOLO11 pose 训练的 DatasetExport")
    if (
        export_by_id is not None
        and export_by_manifest is not None
        and export_by_id.dataset_export_id != export_by_manifest.dataset_export_id
    ):
        raise InvalidRequestError(
            "dataset_export_id 与 dataset_export_manifest_key 不属于同一个 DatasetExport",
            details={
                "dataset_export_id": export_by_id.dataset_export_id,
                "manifest_object_key": dataset_export_manifest_key,
            },
        )
    if dataset_export.project_id != project_id:
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
    if dataset_export.task_type != POSE_TASK_TYPE:
        raise InvalidRequestError(
            "当前 DatasetExport 不是 pose 导出",
            details={
                "dataset_export_id": dataset_export.dataset_export_id,
                "task_type": dataset_export.task_type,
            },
        )
    if (
        dataset_export.manifest_object_key is None
        or not dataset_export.manifest_object_key.strip()
    ):
        raise InvalidRequestError(
            "当前 DatasetExport 缺少 manifest_object_key，不能用于训练",
            details={"dataset_export_id": dataset_export.dataset_export_id},
        )
    require_supported_dataset_export_format(
        model_type=model_type,
        task_type=POSE_TASK_TYPE,
        format_id=dataset_export.format_id,
        dataset_export_id=dataset_export.dataset_export_id,
        unsupported_message="YOLO11 pose 训练只接受 YOLO11 支持的 pose 导出格式",
    )
    return dataset_export


def _get_yolo11_pose_dataset_export(
    *,
    session_factory: SessionFactory,
    dataset_export_id: str,
) -> DatasetExport:
    """按 id 读取一个 YOLO11 pose DatasetExport。"""

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


def _get_yolo11_pose_dataset_export_by_manifest(
    *,
    session_factory: SessionFactory,
    manifest_object_key: str,
) -> DatasetExport:
    """按 manifest object key 读取一个 YOLO11 pose DatasetExport。"""

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


__all__ = ["resolve_yolo11_pose_training_dataset_export"]
