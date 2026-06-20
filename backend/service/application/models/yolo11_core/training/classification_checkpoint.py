"""YOLO11 classification 训练 checkpoint 与 resume 规则。"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class Yolo11ClassificationResumeState:
    """描述 YOLO11 classification resume checkpoint 内容。"""

    model_state_dict: dict[str, object]
    optimizer_state_dict: dict[str, object]
    scheduler_state_dict: dict[str, object] | None
    scaler_state_dict: dict[str, object] | None
    metrics_history: list[dict[str, float]]
    validation_history: list[dict[str, float]]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    global_iteration: int
    saved_max_epochs: int
    saved_batch_size: int
    saved_learning_rate: float
    saved_weight_decay: float
    saved_evaluation_interval: int
    saved_min_lr_ratio: float


def build_yolo11_classification_checkpoint_bytes(
    *,
    epoch: int,
    global_iteration: int,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any | None,
    metrics_history: list[dict[str, float]],
    validation_history: list[dict[str, float]],
    best_metric_value: float,
    best_metric_name: str,
    batch_size: int,
    max_epochs: int,
    learning_rate: float,
    weight_decay: float,
    evaluation_interval: int,
    min_lr_ratio: float,
    torch_module: Any,
) -> bytes:
    """把 YOLO11 classification 训练状态编码为 checkpoint bytes。"""

    payload = {
        "epoch": epoch + 1,
        "global_iteration": global_iteration,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict(),
        "scaler_state_dict": scaler.state_dict() if scaler is not None else None,
        "metrics_history": metrics_history,
        "validation_history": validation_history,
        "best_metric_value": best_metric_value,
        "best_metric_name": best_metric_name,
        "saved_batch_size": batch_size,
        "saved_max_epochs": max_epochs,
        "saved_learning_rate": learning_rate,
        "saved_weight_decay": weight_decay,
        "saved_evaluation_interval": evaluation_interval,
        "saved_min_lr_ratio": min_lr_ratio,
        "model_type": "yolo11",
        "task_type": "classification",
    }
    buffer = io.BytesIO()
    torch_module.save(payload, buffer)
    return buffer.getvalue()


def load_yolo11_classification_resume_state(
    *,
    checkpoint_path: Path,
    torch_module: Any,
) -> Yolo11ClassificationResumeState:
    """读取 YOLO11 classification resume checkpoint。"""

    checkpoint = torch_module.load(
        str(checkpoint_path),
        map_location="cpu",
        weights_only=False,
    )
    if not isinstance(checkpoint, dict):
        raise InvalidRequestError("YOLO11 classification checkpoint 内容不合法")
    return Yolo11ClassificationResumeState(
        model_state_dict=checkpoint.get("model_state_dict", {}),
        optimizer_state_dict=checkpoint.get("optimizer_state_dict", {}),
        scheduler_state_dict=checkpoint.get("scheduler_state_dict"),
        scaler_state_dict=checkpoint.get("scaler_state_dict"),
        metrics_history=checkpoint.get("metrics_history", []),
        validation_history=checkpoint.get("validation_history", []),
        best_metric_value=float(checkpoint.get("best_metric_value", 0.0)),
        best_metric_name=str(checkpoint.get("best_metric_name", "val_top1_accuracy")),
        epoch=int(checkpoint.get("epoch", 0)),
        global_iteration=int(checkpoint.get("global_iteration", 0)),
        saved_max_epochs=int(checkpoint.get("saved_max_epochs", 0)),
        saved_batch_size=int(checkpoint.get("saved_batch_size", 0)),
        saved_learning_rate=float(checkpoint.get("saved_learning_rate", 0.0)),
        saved_weight_decay=float(checkpoint.get("saved_weight_decay", 0.0)),
        saved_evaluation_interval=int(checkpoint.get("saved_evaluation_interval", 0)),
        saved_min_lr_ratio=float(checkpoint.get("saved_min_lr_ratio", 0.0)),
    )


def validate_yolo11_classification_resume_parameters(
    state: Yolo11ClassificationResumeState,
    *,
    batch_size: int,
    max_epochs: int,
    learning_rate: float,
    weight_decay: float,
    evaluation_interval: int,
    min_lr_ratio: float,
) -> None:
    """校验 resume checkpoint 记录的训练参数是否匹配当前请求。"""

    mismatches = []
    if state.saved_batch_size != batch_size:
        mismatches.append(f"batch_size ({state.saved_batch_size} -> {batch_size})")
    if state.saved_max_epochs != max_epochs and max_epochs > 0:
        mismatches.append(f"max_epochs ({state.saved_max_epochs} -> {max_epochs})")
    if abs(state.saved_learning_rate - learning_rate) > 1e-8:
        mismatches.append(
            f"learning_rate ({state.saved_learning_rate} -> {learning_rate})"
        )
    if abs(state.saved_weight_decay - weight_decay) > 1e-8:
        mismatches.append(
            f"weight_decay ({state.saved_weight_decay} -> {weight_decay})"
        )
    if state.saved_evaluation_interval != evaluation_interval:
        mismatches.append(
            f"evaluation_interval ({state.saved_evaluation_interval} -> {evaluation_interval})"
        )
    if abs(state.saved_min_lr_ratio - min_lr_ratio) > 1e-8:
        mismatches.append(
            f"min_lr_ratio ({state.saved_min_lr_ratio} -> {min_lr_ratio})"
        )
    if mismatches:
        raise InvalidRequestError(
            "YOLO11 classification resume 参数与 checkpoint 记录不一致",
            details={"mismatches": mismatches},
        )


def load_yolo11_classification_model_state(
    *,
    model: Any,
    state_dict: dict[str, object],
    device_name: str,
) -> None:
    """把 checkpoint 里的可匹配权重加载进 YOLO11 classification 模型。"""

    filtered = {}
    for key, value in state_dict.items():
        param = model.state_dict().get(key)
        if param is not None and param.shape == value.shape:
            filtered[key] = value
    model.load_state_dict(filtered, strict=False)
    if "cuda" in device_name:
        try:
            model.to(device_name)
        except Exception:
            pass


__all__ = [
    "Yolo11ClassificationResumeState",
    "build_yolo11_classification_checkpoint_bytes",
    "load_yolo11_classification_model_state",
    "load_yolo11_classification_resume_state",
    "validate_yolo11_classification_resume_parameters",
]
