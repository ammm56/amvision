"""YOLO 主线 pose 训练输出登记工具。"""

from __future__ import annotations

from backend.service.application.models.yolo26_model_service import (
    SqlAlchemyYolo26ModelService,
    Yolo26TrainingOutputRegistration,
)
from backend.service.application.models.yolo_primary_pose_training import (
    YOLO_PRIMARY_POSE_IMPLEMENTATION_MODE,
    YoloPrimaryPoseTrainingExecutionResult,
)
from backend.service.application.models.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
    YoloV8TrainingOutputRegistration,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import POSE_TASK_TYPE
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory


YOLO_PRIMARY_POSE_MODEL_SERVICE_MAP: dict[str, tuple[type, type]] = {
    "yolov8": (SqlAlchemyYoloV8ModelService, YoloV8TrainingOutputRegistration),
    "yolo26": (SqlAlchemyYolo26ModelService, Yolo26TrainingOutputRegistration),
}


def resolve_yolo_primary_pose_implementation_mode(model_type: str) -> str:
    """按 model_type 返回 pose 训练实现模式。"""

    return YOLO_PRIMARY_POSE_IMPLEMENTATION_MODE


def register_yolo_primary_pose_training_output_model_version(
    *,
    session_factory: SessionFactory,
    task_record: TaskRecord,
    dataset_export: DatasetExport,
    payload: dict[str, object],
    model_type: str,
    execution_result: YoloPrimaryPoseTrainingExecutionResult,
    checkpoint_object_key: str,
    labels_object_key: str,
    train_metrics_object_key: str,
    summary: dict[str, object],
) -> str:
    """把 pose 训练输出登记为 ModelVersion。"""

    service_cls, registration_cls = YOLO_PRIMARY_POSE_MODEL_SERVICE_MAP[model_type]
    model_service = service_cls(session_factory=session_factory)
    return model_service.register_training_output(
        registration_cls(
            project_id=task_record.project_id,
            training_task_id=task_record.task_id,
            model_name=str(payload.get("output_model_name") or ""),
            model_scale=str(payload.get("model_scale") or ""),
            task_type=POSE_TASK_TYPE,
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
                "kpt_shape": summary.get("kpt_shape"),
                "training_config": dict(summary["training_config"]),
                "metrics_summary": dict(summary["metrics_summary"]),
                "output_files": dict(summary["output_files"]),
                "registration_kind": "best-checkpoint",
                "implementation_mode": resolve_yolo_primary_pose_implementation_mode(
                    model_type
                ),
            },
        )
    )
