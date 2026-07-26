"""YOLO26 classification 训练运行时对象构建。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable

from backend.service.application.models.training.device_selection import (
    resolve_single_training_device_name,
    resolve_torch_amp_device_type,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloUltralyticsTrainingSchedule,
    build_yolo_ultralytics_optimizer,
    build_yolo_ultralytics_scheduler,
)


@dataclass(frozen=True)
class Yolo26ClassificationTrainingRuntime:
    """描述 YOLO26 classification 训练需要复用的运行时对象。"""

    optimizer: Any
    scheduler: Any
    scaler: Any | None
    iterations_per_epoch: int
    total_iterations: int
    autocast_context: Callable[[], Any]
    training_schedule: YoloUltralyticsTrainingSchedule


def resolve_yolo26_classification_training_device(
    *,
    torch_module: Any,
    extra_options: dict[str, object] | None,
) -> str:
    """根据训练参数解析 YOLO26 classification 训练设备。"""

    return resolve_single_training_device_name(
        torch_module=torch_module,
        extra_options=extra_options,
    )


def build_yolo26_classification_training_runtime(
    *,
    torch_module: Any,
    model: Any,
    learning_rate: float,
    weight_decay: float,
    min_lr_ratio: float,
    batch_size: int,
    max_epochs: int,
    train_sample_count: int,
    device_name: str,
    precision: str,
    num_classes: int = 1,
    optimizer_name: str = "auto",
    cosine_schedule: bool = False,
) -> Yolo26ClassificationTrainingRuntime:
    """构建 YOLO26 classification optimizer、scheduler、GradScaler 和 autocast。"""

    optimizer, training_schedule = build_yolo_ultralytics_optimizer(
        torch_module=torch_module,
        model=model,
        num_classes=num_classes,
        batch_size=batch_size,
        train_sample_count=train_sample_count,
        max_epochs=max_epochs,
        optimizer_name=optimizer_name,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        final_lr_ratio=min_lr_ratio,
        cosine_schedule=cosine_schedule,
    )
    iterations_per_epoch = max(
        1, (int(train_sample_count) + int(batch_size) - 1) // int(batch_size)
    )
    total_iterations = max(1, int(max_epochs) * iterations_per_epoch)
    scheduler = build_yolo_ultralytics_scheduler(
        torch_module=torch_module,
        optimizer=optimizer,
        max_epochs=max_epochs,
        final_lr_ratio=min_lr_ratio,
        cosine_schedule=training_schedule.cosine_schedule,
    )
    scaler = (
        torch_module.GradScaler(
            resolve_torch_amp_device_type(device_name),
            enabled=(precision == "fp16"),
        )
        if hasattr(torch_module, "GradScaler")
        else None
    )
    return Yolo26ClassificationTrainingRuntime(
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        iterations_per_epoch=iterations_per_epoch,
        total_iterations=total_iterations,
        autocast_context=build_yolo26_classification_autocast_context(
            torch_module=torch_module,
            precision=precision,
            device_name=device_name,
        ),
        training_schedule=training_schedule,
    )


def build_yolo26_classification_autocast_context(
    *,
    torch_module: Any,
    precision: str,
    device_name: str,
) -> Callable[[], Any]:
    """构建 YOLO26 classification 训练使用的 autocast context。"""

    if precision == "fp16" and "cuda" in device_name:
        return lambda: torch_module.amp.autocast(resolve_torch_amp_device_type(device_name))
    return nullcontext


def move_yolo26_classification_optimizer_state_to_device(
    *,
    optimizer: Any,
    device_name: str,
) -> None:
    """把 YOLO26 classification optimizer state 移到训练设备。"""

    if "cuda" not in device_name:
        return
    for state in optimizer.state.values():
        for key, value in state.items():
            if hasattr(value, "to") and hasattr(value, "device"):
                state[key] = value.to(device_name)


__all__ = [
    "Yolo26ClassificationTrainingRuntime",
    "build_yolo26_classification_autocast_context",
    "build_yolo26_classification_training_runtime",
    "move_yolo26_classification_optimizer_state_to_device",
    "resolve_yolo26_classification_training_device",
]

