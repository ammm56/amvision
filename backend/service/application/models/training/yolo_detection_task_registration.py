"""YOLO detection 训练输出登记工具。"""

from __future__ import annotations

from typing import Any, Callable

from backend.service.application.models.training.detection_training_rules import (
    DetectionTrainingOutputFiles,
    build_detection_metrics_summary_payload,
    build_detection_runtime_summary_payload,
    build_detection_training_config_payload,
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


def register_yolo_detection_checkpoint_model_version(
    *,
    session_factory: SessionFactory,
    model_service_cls: type,
    output_registration_cls: type,
    task_record: TaskRecord,
    request: Any,
    dataset_export: DatasetExport,
    task_result: Any,
    build_training_output_file_id: Callable[..., str],
    model_version_id: str | None = None,
    output_file_token: str | None = None,
    registration_kind: str = "latest-checkpoint",
) -> str:
    """把当前 detection 训练结果中的 checkpoint 登记为 ModelVersion。"""

    model_service = model_service_cls(session_factory=session_factory)
    output_files = DetectionTrainingOutputFiles(
        output_object_prefix=task_result.output_object_prefix,
        checkpoint_object_key=task_result.checkpoint_object_key,
        latest_checkpoint_object_key=task_result.latest_checkpoint_object_key,
        labels_object_key=task_result.labels_object_key,
        metrics_object_key=task_result.metrics_object_key,
        validation_metrics_object_key=task_result.validation_metrics_object_key,
        summary_object_key=task_result.summary_object_key,
    )
    return model_service.register_training_output(
        output_registration_cls(
            project_id=request.project_id,
            training_task_id=task_record.task_id,
            model_version_id=model_version_id,
            model_name=request.output_model_name,
            model_scale=request.model_scale,
            dataset_version_id=task_result.dataset_version_id,
            parent_version_id=request.warm_start_model_version_id,
            checkpoint_file_id=_build_training_output_file_id(
                build_training_output_file_id,
                task_record.task_id,
                "checkpoint",
                output_file_token=output_file_token,
            ),
            checkpoint_file_uri=task_result.checkpoint_object_key,
            labels_file_id=(
                _build_training_output_file_id(
                    build_training_output_file_id,
                    task_record.task_id,
                    "labels",
                    output_file_token=output_file_token,
                )
                if task_result.labels_object_key is not None
                else None
            ),
            labels_file_uri=task_result.labels_object_key,
            metrics_file_id=(
                _build_training_output_file_id(
                    build_training_output_file_id,
                    task_record.task_id,
                    "metrics",
                    output_file_token=output_file_token,
                )
                if task_result.metrics_object_key is not None
                else None
            ),
            metrics_file_uri=task_result.metrics_object_key,
            metadata=_build_yolo_detection_checkpoint_metadata(
                request=request,
                dataset_export=dataset_export,
                task_result=task_result,
                output_files=output_files,
                registration_kind=registration_kind,
            ),
        )
    )


def _build_training_output_file_id(
    build_training_output_file_id: Callable[..., str],
    task_id: str,
    output_name: str,
    *,
    output_file_token: str | None,
) -> str:
    """按可选 token 构建训练输出文件 id。"""

    if output_file_token is None:
        return build_training_output_file_id(task_id, output_name)
    return build_training_output_file_id(
        task_id,
        output_name,
        output_file_token=output_file_token,
    )


def _build_yolo_detection_checkpoint_metadata(
    *,
    request: Any,
    dataset_export: DatasetExport,
    task_result: Any,
    output_files: DetectionTrainingOutputFiles,
    registration_kind: str,
) -> dict[str, object]:
    """构建手动登记 checkpoint 使用的 ModelVersion metadata。"""

    summary = dict(task_result.summary)
    training_config = build_detection_training_config_payload(
        recipe_id=request.recipe_id,
        model_scale=request.model_scale,
        output_model_name=request.output_model_name,
        warm_start_model_version_id=request.warm_start_model_version_id,
        evaluation_interval=request.evaluation_interval,
        max_epochs=request.max_epochs,
        batch_size=request.batch_size,
        gpu_count=request.gpu_count,
        precision=request.precision,
        input_size=request.input_size,
        extra_options=request.extra_options,
    )
    effective_input_size = summary.get("input_size")
    runtime_summary = build_detection_runtime_summary_payload(
        device=_read_optional_str(summary, "device"),
        gpu_count=_read_optional_int(summary, "gpu_count"),
        device_ids=(
            summary.get("device_ids")
            if isinstance(summary.get("device_ids"), list | tuple)
            else None
        ),
        precision=_read_optional_str(summary, "precision"),
        distributed_mode=(
            summary.get("distributed_mode")
            if isinstance(summary.get("distributed_mode"), str)
            else None
        ),
    )
    metrics_summary = build_detection_metrics_summary_payload(
        best_metric_name=task_result.best_metric_name,
        best_metric_value=task_result.best_metric_value,
    )
    return build_detection_training_model_version_metadata(
        dataset_export_id=dataset_export.dataset_export_id,
        manifest_object_key=dataset_export.manifest_object_key,
        category_names=_read_str_tuple(summary.get("category_names")),
        input_size=(
            effective_input_size
            if isinstance(effective_input_size, list | tuple)
            else training_config["input_size"]
        ),
        training_config=training_config,
        runtime_summary=runtime_summary,
        warm_start_summary=dict(summary.get("warm_start") or {}),
        registration_kind=registration_kind,
        output_files=output_files,
        metrics_summary=metrics_summary,
    )


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _read_optional_int(payload: dict[str, object], key: str) -> int | None:
    """从字典中读取可选整数字段。"""

    value = payload.get(key)
    if isinstance(value, int):
        return value
    return None


def _read_str_tuple(value: object) -> tuple[str, ...]:
    """把列表或元组中的有效字符串规整成元组。"""

    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())


__all__ = [
    "register_yolo_detection_checkpoint_model_version",
    "register_yolo_detection_training_output_model_version",
]
