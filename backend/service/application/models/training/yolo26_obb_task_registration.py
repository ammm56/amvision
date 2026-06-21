"""YOLO26 OBB 训练输出登记工具。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.models.registry.yolo26_model_service import (
    SqlAlchemyYolo26ModelService,
    Yolo26TrainingOutputRegistration,
)
from backend.service.application.models.training.yolo26_obb_training import (
    YOLO26_OBB_IMPLEMENTATION_MODE,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import OBB_TASK_TYPE
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory


class Yolo26ObbTrainingResultLike(Protocol):
    """描述登记 YOLO26 OBB 训练输出所需的执行结果字段。"""

    labels: tuple[str, ...]


def resolve_yolo26_obb_implementation_mode() -> str:
    """返回 YOLO26 OBB 训练实现标记。"""

    return YOLO26_OBB_IMPLEMENTATION_MODE


def register_yolo26_obb_training_output_model_version(
    *,
    session_factory: SessionFactory,
    task_record: TaskRecord,
    dataset_export: DatasetExport,
    payload: dict[str, object],
    execution_result: Yolo26ObbTrainingResultLike,
    checkpoint_object_key: str,
    labels_object_key: str,
    train_metrics_object_key: str,
    summary: dict[str, object],
) -> str:
    """把 YOLO26 OBB 训练输出登记为 ModelVersion。"""

    model_service = SqlAlchemyYolo26ModelService(session_factory=session_factory)
    return model_service.register_training_output(
        Yolo26TrainingOutputRegistration(
            project_id=task_record.project_id,
            training_task_id=task_record.task_id,
            model_name=str(payload.get("output_model_name") or ""),
            model_scale=str(payload.get("model_scale") or ""),
            task_type=OBB_TASK_TYPE,
            dataset_version_id=dataset_export.dataset_version_id,
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
                "registration_kind": "best-checkpoint",
                "implementation_mode": resolve_yolo26_obb_implementation_mode(),
            },
        )
    )


__all__ = [
    "register_yolo26_obb_training_output_model_version",
    "resolve_yolo26_obb_implementation_mode",
]
