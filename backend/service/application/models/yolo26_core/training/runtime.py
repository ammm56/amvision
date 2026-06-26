"""YOLO26 detection 训练运行时对象构建。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolo_core_common.training import (
    YoloUltralyticsTrainingSchedule,
    build_yolo_ultralytics_optimizer,
    build_yolo_ultralytics_scheduler,
)


@dataclass(frozen=True)
class Yolo26DetectionTrainingRuntime:
    """描述 YOLO26 detection 训练需要复用的运行时对象。"""

    optimizer: Any
    scheduler: Any
    scaler: Any
    schedule: YoloUltralyticsTrainingSchedule


def build_yolo26_detection_training_runtime(
    *,
    torch_module: Any,
    model: Any,
    learning_rate: float,
    weight_decay: float,
    max_epochs: int,
    min_lr_ratio: float,
    batch_size: int,
    train_sample_count: int,
    num_classes: int,
    device: str,
    runtime_precision: str,
) -> Yolo26DetectionTrainingRuntime:
    """构建 YOLO26 detection optimizer、scheduler 和 GradScaler。"""

    optimizer, schedule = build_yolo_ultralytics_optimizer(
        torch_module=torch_module,
        model=model,
        num_classes=num_classes,
        batch_size=batch_size,
        train_sample_count=train_sample_count,
        max_epochs=max_epochs,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        final_lr_ratio=min_lr_ratio,
    )
    scheduler = build_yolo_ultralytics_scheduler(
        torch_module=torch_module,
        optimizer=optimizer,
        max_epochs=max_epochs,
        final_lr_ratio=min_lr_ratio,
    )
    scaler_enabled = device.startswith("cuda") and runtime_precision == "fp16"
    amp_module = getattr(torch_module, "amp", None)
    grad_scaler_cls = (
        getattr(amp_module, "GradScaler", None) if amp_module is not None else None
    )
    if grad_scaler_cls is not None:
        scaler = grad_scaler_cls("cuda", enabled=scaler_enabled)
    else:
        scaler = torch_module.cuda.amp.GradScaler(enabled=scaler_enabled)
    return Yolo26DetectionTrainingRuntime(
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        schedule=schedule,
    )


def move_yolo26_optimizer_state_to_device(*, optimizer: Any, device: str) -> None:
    """把 YOLO26 optimizer 状态里的 tensor 移到训练设备。"""

    for state in optimizer.state.values():
        if not isinstance(state, dict):
            continue
        for key, value in tuple(state.items()):
            if hasattr(value, "to"):
                state[key] = value.to(device=device)


def build_yolo26_autocast_context(
    *,
    torch_module: Any,
    device: str,
    runtime_precision: str,
) -> Any:
    """构建 YOLO26 detection 训练使用的 autocast context。"""

    if not device.startswith("cuda") or runtime_precision != "fp16":
        return nullcontext
    amp_module = getattr(torch_module, "amp", None)
    autocast = getattr(amp_module, "autocast", None) if amp_module is not None else None
    if callable(autocast):
        return lambda: autocast("cuda", enabled=True)
    return lambda: torch_module.cuda.amp.autocast(enabled=True)


__all__ = [
    "Yolo26DetectionTrainingRuntime",
    "build_yolo26_autocast_context",
    "build_yolo26_detection_training_runtime",
    "move_yolo26_optimizer_state_to_device",
]
