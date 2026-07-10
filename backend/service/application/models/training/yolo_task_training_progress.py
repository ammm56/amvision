"""YOLO 非 detection 训练进度、指标和任务事件回写工具。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    SqlAlchemyTaskService,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


class YoloTaskEpochProgressLike(Protocol):
    """描述 YOLO task 训练 epoch progress 需要提供的字段。"""

    epoch: int
    max_epochs: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


def append_yolo_task_epoch_progress(
    *,
    task_service: SqlAlchemyTaskService,
    task_id: str,
    model_label: str,
    task_type: str,
    model_type: str,
    attempt_no: int,
    output_prefix: str,
    train_metrics_object_key: str,
    progress: YoloTaskEpochProgressLike,
    dataset_storage: LocalDatasetStorage,
    implementation_mode: str,
) -> None:
    """写出 YOLO task 训练 epoch 指标并追加任务进度事件。"""

    train_payload = build_yolo_task_train_metrics_payload(
        progress=progress,
        task_type=task_type,
        model_type=model_type,
        implementation_mode=implementation_mode,
    )
    dataset_storage.write_json(train_metrics_object_key, train_payload)
    task_service.append_task_event(
        build_yolo_task_epoch_progress_event(
            task_id=task_id,
            model_label=model_label,
            task_type=task_type,
            model_type=model_type,
            attempt_no=attempt_no,
            output_prefix=output_prefix,
            train_metrics_object_key=train_metrics_object_key,
            progress=progress,
        )
    )


def build_yolo_task_train_metrics_payload(
    *,
    progress: YoloTaskEpochProgressLike,
    task_type: str,
    model_type: str,
    implementation_mode: str,
) -> dict[str, object]:
    """构建 YOLO task 训练中的 train-metrics.json 内容。"""

    current_epoch = progress.epoch + 1
    train_metrics = {"epoch": progress.epoch, **dict(progress.train_metrics)}
    return {
        "task_type": task_type,
        "model_type": model_type,
        "implementation_mode": implementation_mode,
        "epoch": current_epoch,
        "epoch_index": progress.epoch,
        "max_epochs": progress.max_epochs,
        "input_size": list(progress.input_size),
        "learning_rate": progress.learning_rate,
        "final_metrics": dict(progress.train_metrics),
        "epoch_history": [train_metrics],
    }


def build_yolo_task_epoch_progress_event(
    *,
    task_id: str,
    model_label: str,
    task_type: str,
    model_type: str,
    attempt_no: int,
    output_prefix: str,
    train_metrics_object_key: str,
    progress: YoloTaskEpochProgressLike,
) -> AppendTaskEventRequest:
    """构建 YOLO task epoch 进度事件。"""

    current_epoch = progress.epoch + 1
    percent = build_yolo_task_progress_percent(
        current_epoch=current_epoch,
        max_epochs=progress.max_epochs,
    )
    progress_payload: dict[str, object] = {
        "stage": "running",
        "task_type": task_type,
        "model_type": model_type,
        "epoch": current_epoch,
        "epoch_index": progress.epoch,
        "max_epochs": progress.max_epochs,
        "percent": percent,
        "input_size": list(progress.input_size),
        "learning_rate": progress.learning_rate,
        "train_metrics": dict(progress.train_metrics),
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
            },
        },
    )


def build_yolo_task_progress_percent(
    *,
    current_epoch: int,
    max_epochs: int,
) -> float:
    """按 epoch 计算 YOLO task 训练进度百分比。"""

    return round(
        min(95.0, 10.0 + (80.0 * max(0, current_epoch)) / max(1, max_epochs)),
        2,
    )
