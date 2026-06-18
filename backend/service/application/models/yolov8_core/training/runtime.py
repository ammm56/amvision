"""YOLOv8 detection 训练运行时对象构建。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class YoloV8DetectionTrainingRuntime:
    """描述 YOLOv8 detection 训练需要复用的运行时对象。"""

    optimizer: Any
    scheduler: Any
    scaler: Any


def build_yolov8_detection_training_runtime(
    *,
    torch_module: Any,
    model: Any,
    learning_rate: float,
    weight_decay: float,
    max_epochs: int,
    min_lr_ratio: float,
    device: str,
    runtime_precision: str,
) -> YoloV8DetectionTrainingRuntime:
    """构建 YOLOv8 detection optimizer、scheduler 和 GradScaler。"""

    optimizer = torch_module.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    scheduler = torch_module.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=max_epochs,
        eta_min=learning_rate * min_lr_ratio,
    )
    scaler_enabled = device.startswith("cuda") and runtime_precision == "fp16"
    amp_module = getattr(torch_module, "amp", None)
    grad_scaler_cls = getattr(amp_module, "GradScaler", None) if amp_module is not None else None
    if grad_scaler_cls is not None:
        scaler = grad_scaler_cls("cuda", enabled=scaler_enabled)
    else:
        scaler = torch_module.cuda.amp.GradScaler(enabled=scaler_enabled)
    return YoloV8DetectionTrainingRuntime(
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
    )


def move_yolov8_optimizer_state_to_device(*, optimizer: Any, device: str) -> None:
    """把 YOLOv8 optimizer 状态里的 tensor 移到训练设备。"""

    for state in optimizer.state.values():
        if not isinstance(state, dict):
            continue
        for key, value in tuple(state.items()):
            if hasattr(value, "to"):
                state[key] = value.to(device=device)


def build_yolov8_autocast_context(
    *,
    torch_module: Any,
    device: str,
    runtime_precision: str,
) -> Any:
    """构建 YOLOv8 detection 训练使用的 autocast context。"""

    if not device.startswith("cuda") or runtime_precision != "fp16":
        return nullcontext
    amp_module = getattr(torch_module, "amp", None)
    autocast = getattr(amp_module, "autocast", None) if amp_module is not None else None
    if callable(autocast):
        return lambda: autocast("cuda", enabled=True)
    return lambda: torch_module.cuda.amp.autocast(enabled=True)


__all__ = [
    "YoloV8DetectionTrainingRuntime",
    "build_yolov8_autocast_context",
    "build_yolov8_detection_training_runtime",
    "move_yolov8_optimizer_state_to_device",
]
