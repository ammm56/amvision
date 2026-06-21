"""YOLO detection 训练输出登记工具。"""

from __future__ import annotations

from typing import Any, Callable

from backend.service.application.models.training.detection_training_rules import (
    DetectionTrainingOutputFiles,
    build_detection_metrics_summary_payload,
    build_detection_runtime_summary_payload,
    build_detection_training_model_version_metadata,
)
from backend.service.application.models.training.yolo_detection_training_execution import (
    YoloDetectionTrainingExecutionResult,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory


def register_yolo_detection_training_output_model_version(
    *,
    session_factory: SessionFactory,
    model_service_cls: type,
    output_registration_cls: type,
    task_record: TaskRecord,
    request: Any,
    dataset_export: DatasetExport,
    output_files: DetectionTrainingOutputFiles,
    execution_result: YoloDetectionTrainingExecutionResult,
    summary: dict[str, object],
    build_training_output_file_id: Callable[[str, str], str],
) -> str:
    """把 detection 训练输出登记为 ModelVersion，并写入对应 ModelFile 记录。"""

    model_service = model_service_cls(session_factory=session_factory)
    runtime_summary = build_detection_runtime_summary_payload(
        device=execution_result.device,
        gpu_count=execution_result.gpu_count,
        device_ids=execution_result.device_ids,
        precision=execution_result.precision,
        distributed_mode=execution_result.distributed_mode,
    )
    metrics_summary = build_detection_metrics_summary_payload(
        best_metric_name=execution_result.best_metric_name,
        best_metric_value=execution_result.best_metric_value,
    )
    return model_service.register_training_output(
        output_registration_cls(
            project_id=request.project_id,
            training_task_id=task_record.task_id,
            model_name=request.output_model_name,
            model_scale=request.model_scale,
            dataset_version_id=dataset_export.dataset_version_id,
            parent_version_id=request.warm_start_model_version_id,
            checkpoint_file_id=build_training_output_file_id(
                task_record.task_id, "checkpoint"
            ),
            checkpoint_file_uri=output_files.checkpoint_object_key,
            labels_file_id=build_training_output_file_id(task_record.task_id, "labels"),
            labels_file_uri=output_files.labels_object_key,
            metrics_file_id=build_training_output_file_id(
                task_record.task_id, "metrics"
            ),
            metrics_file_uri=output_files.metrics_object_key,
            metadata=build_detection_training_model_version_metadata(
                dataset_export_id=dataset_export.dataset_export_id,
                manifest_object_key=dataset_export.manifest_object_key,
                category_names=execution_result.category_names,
                input_size=execution_result.input_size,
                training_config=dict(summary["training_config"]),
                runtime_summary=runtime_summary,
                warm_start_summary=dict(execution_result.warm_start_summary),
                registration_kind="best-checkpoint",
                output_files=output_files,
                metrics_summary=metrics_summary,
            ),
        )
    )


__all__ = [
    "register_yolo_detection_training_output_model_version",
]
