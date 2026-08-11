"""YOLO 非 detection 训练进度、指标和任务事件回写工具。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.models.training.metric_policy import (
    serialize_training_metric,
)
from backend.service.application.models.yolo_core_common.training import (
    build_yolo_epoch_history_item,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    SqlAlchemyTaskService,
)
from backend.service.domain.models.model_input_spec import serialize_spatial_size_hw
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
    validation_metrics_object_key: str | None = None,
) -> None:
    """写出 YOLO task 训练 epoch 指标并追加任务进度事件。"""

    previous_train_payload = _read_existing_metrics_payload(
        dataset_storage=dataset_storage,
        object_key=train_metrics_object_key,
    )
    train_payload = build_yolo_task_train_metrics_payload(
        progress=progress,
        task_type=task_type,
        model_type=model_type,
        implementation_mode=implementation_mode,
        previous_payload=previous_train_payload,
    )
    dataset_storage.write_json(train_metrics_object_key, train_payload)
    validation_metrics = _read_progress_validation_metrics(progress)
    if validation_metrics and validation_metrics_object_key is not None:
        previous_validation_payload = _read_existing_metrics_payload(
            dataset_storage=dataset_storage,
            object_key=validation_metrics_object_key,
        )
        dataset_storage.write_json(
            validation_metrics_object_key,
            build_yolo_task_validation_metrics_payload(
                progress=progress,
                validation_metrics=validation_metrics,
                task_type=task_type,
                model_type=model_type,
                implementation_mode=implementation_mode,
                previous_payload=previous_validation_payload,
            ),
        )
    task_service.append_task_event(
        build_yolo_task_epoch_progress_event(
            task_id=task_id,
            model_label=model_label,
            task_type=task_type,
            model_type=model_type,
            attempt_no=attempt_no,
            output_prefix=output_prefix,
            train_metrics_object_key=train_metrics_object_key,
            validation_metrics_object_key=(
                validation_metrics_object_key if validation_metrics else None
            ),
            progress=progress,
        )
    )


def build_yolo_task_train_metrics_payload(
    *,
    progress: YoloTaskEpochProgressLike,
    task_type: str,
    model_type: str,
    implementation_mode: str,
    previous_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    """构建 YOLO task 训练中的 train-metrics.json 内容。"""

    current_epoch = progress.epoch + 1
    train_metrics = build_yolo_epoch_history_item(
        epoch_index=progress.epoch,
        metrics=progress.train_metrics,
    )
    return {
        "task_type": task_type,
        "model_type": model_type,
        "implementation_mode": implementation_mode,
        "epoch": current_epoch,
        "epoch_index": progress.epoch,
        "max_epochs": progress.max_epochs,
        "input_size": serialize_spatial_size_hw(progress.input_size),
        "learning_rate": progress.learning_rate,
        "final_metrics": dict(progress.train_metrics),
        "epoch_history": _merge_epoch_history(
            previous_payload=previous_payload,
            current_item=train_metrics,
            maximum_entries=progress.max_epochs,
        ),
    }


def build_yolo_task_validation_metrics_payload(
    *,
    progress: YoloTaskEpochProgressLike,
    validation_metrics: dict[str, float],
    task_type: str,
    model_type: str,
    implementation_mode: str,
    previous_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    """构建训练过程中可立即读取的 validation-metrics.json。"""

    current_epoch = progress.epoch + 1
    return {
        "task_type": task_type,
        "model_type": model_type,
        "implementation_mode": implementation_mode,
        "epoch": current_epoch,
        "epoch_index": progress.epoch,
        "max_epochs": progress.max_epochs,
        "input_size": serialize_spatial_size_hw(progress.input_size),
        "final_metrics": dict(validation_metrics),
        "epoch_history": _merge_epoch_history(
            previous_payload=previous_payload,
            current_item=build_yolo_epoch_history_item(
                epoch_index=progress.epoch,
                metrics=validation_metrics,
            ),
            maximum_entries=progress.max_epochs,
        ),
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
    validation_metrics_object_key: str | None = None,
    progress: YoloTaskEpochProgressLike,
) -> AppendTaskEventRequest:
    """构建 YOLO task epoch 进度事件。"""

    current_epoch = progress.epoch + 1
    percent = build_yolo_task_progress_percent(
        current_epoch=current_epoch,
        max_epochs=progress.max_epochs,
    )
    validation_metrics = _read_progress_validation_metrics(progress)
    best_metric_value = serialize_training_metric(
        getattr(progress, "best_metric_value", None),
        minimum=0.0,
        maximum=1.0,
    )
    best_metric_name = getattr(progress, "best_metric_name", None)
    progress_payload: dict[str, object] = {
        "stage": "running",
        "task_type": task_type,
        "model_type": model_type,
        "epoch": current_epoch,
        "epoch_index": progress.epoch,
        "max_epochs": progress.max_epochs,
        "percent": percent,
        "input_size": serialize_spatial_size_hw(progress.input_size),
        "learning_rate": progress.learning_rate,
        "train_metrics": dict(progress.train_metrics),
    }
    if validation_metrics:
        progress_payload["validation_metrics"] = validation_metrics
    if best_metric_value is not None:
        progress_payload["best_metric_value"] = best_metric_value
        if isinstance(best_metric_name, str) and best_metric_name:
            progress_payload["best_metric_name"] = best_metric_name
    result_payload: dict[str, object] = {
        "output_prefix": output_prefix,
        "output_object_prefix": output_prefix,
        "metrics_object_key": train_metrics_object_key,
    }
    if validation_metrics_object_key is not None:
        result_payload["validation_metrics_object_key"] = (
            validation_metrics_object_key
        )
    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="progress",
        message=f"{model_label} epoch {current_epoch}/{progress.max_epochs}",
        payload={
            "state": "running",
            "attempt_no": attempt_no,
            "progress": progress_payload,
            "result": result_payload,
        },
    )


def _read_progress_validation_metrics(
    progress: YoloTaskEpochProgressLike,
) -> dict[str, float]:
    """从支持 validation 的进度对象读取有限的公开指标。"""

    payload = getattr(progress, "validation_metrics", None)
    if not isinstance(payload, dict):
        return {}
    return {
        str(name): float(value)
        for name, value in payload.items()
        if serialize_training_metric(value) is not None
    }


def _read_existing_metrics_payload(
    *,
    dataset_storage: LocalDatasetStorage,
    object_key: str,
) -> dict[str, object] | None:
    """读取可恢复的历史快照；缺失或损坏文件按空历史处理。"""

    if not dataset_storage.resolve(object_key).is_file():
        return None
    try:
        payload = dataset_storage.read_json(object_key)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _merge_epoch_history(
    *,
    previous_payload: dict[str, object] | None,
    current_item: dict[str, object],
    maximum_entries: int,
) -> list[dict[str, object]]:
    """按 epoch_index 合并历史，支持 resume 覆盖且保持内存和文件有界。"""

    history_by_epoch: dict[int, dict[str, object]] = {}
    previous_history = (
        previous_payload.get("epoch_history")
        if isinstance(previous_payload, dict)
        else None
    )
    if isinstance(previous_history, list):
        for item in previous_history:
            if not isinstance(item, dict):
                continue
            epoch_index = item.get("epoch_index")
            if (
                isinstance(epoch_index, int)
                and not isinstance(epoch_index, bool)
                and epoch_index >= 0
            ):
                history_by_epoch[epoch_index] = dict(item)
    current_epoch_index = current_item.get("epoch_index")
    if not isinstance(current_epoch_index, int) or isinstance(
        current_epoch_index,
        bool,
    ):
        raise ValueError("current_item.epoch_index 必须是整数")
    history_by_epoch[current_epoch_index] = dict(current_item)
    ordered = [history_by_epoch[index] for index in sorted(history_by_epoch)]
    return ordered[-max(1, int(maximum_entries)) :]


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
