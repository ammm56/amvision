"""segmentation 训练输出登记工具。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.models.catalog.rfdetr import (
    RfdetrTrainingOutputRegistration,
    SqlAlchemyRfdetrModelService,
)
from backend.service.application.models.training.rfdetr_segmentation import (
    RFDETR_SEGMENTATION_IMPLEMENTATION_MODE,
)
from backend.service.application.models.training.yolov8_segmentation_training import (
    YOLOV8_SEGMENTATION_IMPLEMENTATION_MODE,
)
from backend.service.application.models.registry.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
    YoloV8TrainingOutputRegistration,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory


SEGMENTATION_TRAINING_MODEL_SERVICE_MAP: dict[str, tuple[type, type]] = {
    "yolov8": (SqlAlchemyYoloV8ModelService, YoloV8TrainingOutputRegistration),
    "rfdetr": (SqlAlchemyRfdetrModelService, RfdetrTrainingOutputRegistration),
}


class SegmentationTrainingResultLike(Protocol):
    """描述登记 segmentation 训练输出所需的执行结果字段。"""

    labels: tuple[str, ...]


def resolve_segmentation_implementation_mode(model_type: str) -> str:
    """按模型分类返回 segmentation 训练实现标记。"""

    if model_type == "rfdetr":
        return RFDETR_SEGMENTATION_IMPLEMENTATION_MODE
    return YOLOV8_SEGMENTATION_IMPLEMENTATION_MODE


def register_segmentation_training_output_model_version(
    *,
    session_factory: SessionFactory,
    task_record: TaskRecord,
    dataset_export: DatasetExport,
    payload: dict[str, object],
    model_type: str,
    execution_result: SegmentationTrainingResultLike,
    checkpoint_object_key: str,
    labels_object_key: str,
    train_metrics_object_key: str,
    summary: dict[str, object],
) -> str:
    """把 segmentation 训练输出登记为 ModelVersion。"""

    service_cls, registration_cls = SEGMENTATION_TRAINING_MODEL_SERVICE_MAP[
        model_type
    ]
    model_service = service_cls(session_factory=session_factory)
    return model_service.register_training_output(
        registration_cls(
            project_id=task_record.project_id,
            training_task_id=task_record.task_id,
            model_name=str(payload.get("output_model_name") or ""),
            model_scale=str(payload.get("model_scale") or ""),
            task_type=SEGMENTATION_TASK_TYPE,
            dataset_version_id=dataset_export.dataset_version_id,
            parent_version_id=_read_optional_parent_version_id(payload),
            checkpoint_file_id=f"{task_record.task_id}-checkpoint",
            checkpoint_file_uri=checkpoint_object_key,
            labels_file_id=f"{task_record.task_id}-labels",
            labels_file_uri=labels_object_key,
            metrics_file_id=f"{task_record.task_id}-metrics",
            metrics_file_uri=train_metrics_object_key,
            metadata={
                "dataset_export_id": dataset_export.dataset_export_id,
                "manifest_object_key": dataset_export.manifest_object_key,
                "category_names": list(execution_result.labels),
                "input_size": summary.get("input_size"),
                "training_config": dict(summary["training_config"]),
                "metrics_summary": dict(summary["metrics_summary"]),
                "output_files": dict(summary["output_files"]),
                "warm_start": dict(summary.get("warm_start") or {}),
                "registration_kind": "best-checkpoint",
                "implementation_mode": resolve_segmentation_implementation_mode(
                    model_type
                ),
            },
        )
    )


def _read_optional_parent_version_id(payload: dict[str, object]) -> str | None:
    """读取可选 warm start 父 ModelVersion id。"""

    value = payload.get("warm_start_model_version_id")
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
