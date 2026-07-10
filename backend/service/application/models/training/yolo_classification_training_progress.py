"""YOLO classification 训练进度、指标和输出文件回写工具。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    SqlAlchemyTaskService,
)
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


class YoloClassificationEpochProgressLike(Protocol):
    """描述分类训练 epoch progress 需要提供的字段。"""

    epoch: int
    max_epochs: int
    evaluation_interval: int
    validation_ran: bool
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    train_metrics_snapshot: dict[str, object]
    validation_metrics_snapshot: dict[str, object]
    current_metric_name: str
    current_metric_value: float | None
    best_metric_name: str
    best_metric_value: float


class YoloClassificationSavePointLike(Protocol):
    """描述分类训练 savepoint 需要提供的字段。"""

    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_name: str
    best_metric_value: float
    epoch: int
    learning_rate: float


def append_yolo_classification_epoch_progress(
    *,
    task_service: SqlAlchemyTaskService,
    task_id: str,
    model_label: str,
    model_type: str,
    attempt_no: int,
    output_prefix: str,
    train_metrics_object_key: str,
    validation_metrics_object_key: str,
    progress: YoloClassificationEpochProgressLike,
    dataset_storage: LocalDatasetStorage,
    implementation_mode: str,
) -> None:
    """写出分类训练 epoch 指标并追加任务进度事件。"""

    train_payload = build_yolo_classification_train_metrics_payload(
        progress=progress,
        implementation_mode=implementation_mode,
    )
    validation_payload = build_yolo_classification_validation_metrics_payload(
        progress=progress
    )
    dataset_storage.write_json(train_metrics_object_key, train_payload)
    dataset_storage.write_json(validation_metrics_object_key, validation_payload)
    task_service.append_task_event(
        build_yolo_classification_epoch_progress_event(
            task_id=task_id,
            model_label=model_label,
            model_type=model_type,
            attempt_no=attempt_no,
            output_prefix=output_prefix,
            train_metrics_object_key=train_metrics_object_key,
            validation_metrics_object_key=validation_metrics_object_key,
            progress=progress,
        )
    )


def build_yolo_classification_train_metrics_payload(
    *,
    progress: YoloClassificationEpochProgressLike,
    implementation_mode: str,
) -> dict[str, object]:
    """构建分类训练 train-metrics.json 内容。"""

    payload = dict(progress.train_metrics_snapshot)
    payload["implementation_mode"] = implementation_mode
    payload["best_metric_name"] = progress.best_metric_name
    payload["best_metric_value"] = progress.best_metric_value
    return payload


def build_yolo_classification_validation_metrics_payload(
    *,
    progress: YoloClassificationEpochProgressLike,
) -> dict[str, object]:
    """构建分类训练 validation-metrics.json 内容。"""

    payload = dict(progress.validation_metrics_snapshot)
    payload["best_metric_name"] = progress.best_metric_name
    payload["best_metric_value"] = progress.best_metric_value
    payload["current_metric_name"] = progress.current_metric_name
    payload["current_metric_value"] = progress.current_metric_value
    return payload


def build_yolo_classification_epoch_progress_event(
    *,
    task_id: str,
    model_label: str,
    model_type: str,
    attempt_no: int,
    output_prefix: str,
    train_metrics_object_key: str,
    validation_metrics_object_key: str,
    progress: YoloClassificationEpochProgressLike,
) -> AppendTaskEventRequest:
    """构建分类训练 epoch 进度事件。"""

    current_epoch = progress.epoch + 1
    percent = build_yolo_classification_progress_percent(
        current_epoch=current_epoch,
        max_epochs=progress.max_epochs,
    )
    progress_payload: dict[str, object] = {
        "stage": "running",
        "task_type": CLASSIFICATION_TASK_TYPE,
        "model_type": model_type,
        "epoch": current_epoch,
        "epoch_index": progress.epoch,
        "max_epochs": progress.max_epochs,
        "percent": percent,
        "evaluation_interval": progress.evaluation_interval,
        "validation_ran": progress.validation_ran,
        "input_size": list(progress.input_size),
        "learning_rate": progress.learning_rate,
        "train_metrics": dict(progress.train_metrics),
        "validation_metrics": dict(progress.validation_metrics),
        "current_metric_name": progress.current_metric_name,
        "current_metric_value": progress.current_metric_value,
        "best_metric_name": progress.best_metric_name,
        "best_metric_value": progress.best_metric_value,
    }
    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="progress",
        message=f"{model_label} epoch {current_epoch}/{progress.max_epochs}",
        payload={
            "state": "running",
            "attempt_no": attempt_no,
            "progress": progress_payload,
            "result": {
                "output_prefix": output_prefix,
                "output_object_prefix": output_prefix,
                "metrics_object_key": train_metrics_object_key,
                "validation_metrics_object_key": validation_metrics_object_key,
                "best_metric_name": progress.best_metric_name,
                "best_metric_value": progress.best_metric_value,
            },
        },
    )


def build_yolo_classification_progress_percent(
    *,
    current_epoch: int,
    max_epochs: int,
) -> float:
    """按 epoch 计算分类训练进度百分比。"""

    return round(
        min(95.0, 10.0 + (80.0 * max(0, current_epoch)) / max(1, max_epochs)),
        2,
    )


def build_yolo_classification_output_files_summary(
    *,
    output_prefix: str,
    checkpoint_object_key: str,
    latest_checkpoint_object_key: str,
    labels_object_key: str,
    metrics_object_key: str,
    validation_metrics_object_key: str,
    summary_object_key: str,
) -> dict[str, object]:
    """构建 classification summary 中的 output_files 字段。"""

    return {
        "output_object_prefix": output_prefix,
        "checkpoint_object_key": checkpoint_object_key,
        "latest_checkpoint_object_key": latest_checkpoint_object_key,
        "labels_object_key": labels_object_key,
        "metrics_object_key": metrics_object_key,
        "validation_metrics_object_key": validation_metrics_object_key,
        "summary_object_key": summary_object_key,
    }


def build_yolo_classification_savepoint_summary(
    *,
    task_id: str,
    status: str,
    output_prefix: str,
    dataset_export_id: str,
    dataset_export_manifest_key: str | None,
    dataset_version_id: str,
    format_id: str,
    model_type: str,
    model_scale: str,
    output_model_name: str,
    savepoint: YoloClassificationSavePointLike,
    checkpoint_object_key: str,
    latest_checkpoint_object_key: str,
    labels_object_key: str,
    train_metrics_object_key: str,
    validation_metrics_object_key: str,
    summary_object_key: str,
) -> dict[str, object]:
    """构建分类训练 savepoint 阶段的 summary。"""

    return {
        "task_id": task_id,
        "status": status,
        "task_type": CLASSIFICATION_TASK_TYPE,
        "model_type": model_type,
        "model_scale": model_scale,
        "output_model_name": output_model_name,
        "dataset_export_id": dataset_export_id,
        "dataset_export_manifest_key": dataset_export_manifest_key,
        "dataset_version_id": dataset_version_id,
        "format_id": format_id,
        "output_prefix": output_prefix,
        "output_object_prefix": output_prefix,
        "latest_checkpoint_epoch": savepoint.epoch,
        "best_metric_name": savepoint.best_metric_name,
        "best_metric_value": savepoint.best_metric_value,
        "train_metrics": dict(savepoint.train_metrics),
        "validation_metrics": dict(savepoint.validation_metrics),
        "output_files": build_yolo_classification_output_files_summary(
            output_prefix=output_prefix,
            checkpoint_object_key=checkpoint_object_key,
            latest_checkpoint_object_key=latest_checkpoint_object_key,
            labels_object_key=labels_object_key,
            metrics_object_key=train_metrics_object_key,
            validation_metrics_object_key=validation_metrics_object_key,
            summary_object_key=summary_object_key,
        ),
    }


__all__ = [
    "append_yolo_classification_epoch_progress",
    "build_yolo_classification_output_files_summary",
    "build_yolo_classification_savepoint_summary",
]
