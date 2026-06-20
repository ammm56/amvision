"""YOLO11 classification 训练运行时对象构建。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Yolo11ClassificationTrainingRuntime:
    """描述 YOLO11 classification 训练需要复用的运行时对象。"""

    optimizer: Any
    scheduler: Any
    scaler: Any | None
    iterations_per_epoch: int
    total_iterations: int
    autocast_context: Callable[[], Any]


def resolve_yolo11_classification_training_device(
    *,
    torch_module: Any,
    extra_options: dict[str, object] | None,
) -> str:
    """根据训练参数解析 YOLO11 classification 训练设备。"""

    requested = str((extra_options or {}).get("device", "cpu")).strip().lower()
    if requested == "cuda" and torch_module.cuda.is_available():
        return "cuda:0"
    if requested.startswith("cuda:") and torch_module.cuda.is_available():
        return requested
    return "cpu"


def build_yolo11_classification_training_runtime(
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
) -> Yolo11ClassificationTrainingRuntime:
    """构建 YOLO11 classification optimizer、scheduler、GradScaler 和 autocast。"""

    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch_module.optim.AdamW(
        trainable_params,
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    iterations_per_epoch = max(
        1, (int(train_sample_count) + int(batch_size) - 1) // int(batch_size)
    )
    total_iterations = max(1, int(max_epochs) * iterations_per_epoch)
    scheduler = torch_module.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=total_iterations,
        eta_min=learning_rate * min_lr_ratio,
    )
    scaler = (
        torch_module.GradScaler(
            device_name,
            enabled=(precision == "fp16"),
        )
        if hasattr(torch_module, "GradScaler")
        else None
    )
    return Yolo11ClassificationTrainingRuntime(
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        iterations_per_epoch=iterations_per_epoch,
        total_iterations=total_iterations,
        autocast_context=build_yolo11_classification_autocast_context(
            torch_module=torch_module,
            precision=precision,
            device_name=device_name,
        ),
    )


def build_yolo11_classification_autocast_context(
    *,
    torch_module: Any,
    precision: str,
    device_name: str,
) -> Callable[[], Any]:
    """构建 YOLO11 classification 训练使用的 autocast context。"""

    if precision == "fp16" and "cuda" in device_name:
        return lambda: torch_module.amp.autocast(device_name)
    return nullcontext


def move_yolo11_classification_optimizer_state_to_device(
    *,
    optimizer: Any,
    device_name: str,
) -> None:
    """把 YOLO11 classification optimizer state 移到训练设备。"""

    if "cuda" not in device_name:
        return
    for state in optimizer.state.values():
        for key, value in state.items():
            if hasattr(value, "to") and hasattr(value, "device"):
                try:
                    state[key] = value.to(device_name)
                except Exception:
                    pass


__all__ = [
    "Yolo11ClassificationTrainingRuntime",
    "build_yolo11_classification_autocast_context",
    "build_yolo11_classification_training_runtime",
    "move_yolo11_classification_optimizer_state_to_device",
    "resolve_yolo11_classification_training_device",
]
