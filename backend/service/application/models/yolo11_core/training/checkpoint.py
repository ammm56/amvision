"""YOLO11 detection 训练 checkpoint 构建。"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class Yolo11DetectionEpochCheckpointUpdate:
    """描述 YOLO11 detection 一个 epoch 后的 checkpoint 更新结果。"""

    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes
    best_metric_value: float


def build_yolo11_detection_checkpoint_state(
    *,
    model: Any,
    ema_model: Any | None,
    ema_updates: int | None,
    optimizer: Any,
    scheduler: Any,
    scaler: Any,
    model_type: str,
    model_scale: str,
    category_names: tuple[str, ...],
    input_size: tuple[int, int],
    batch_size: int,
    max_epochs: int,
    epoch: int,
    precision: str,
    validation_split_name: str | None,
    evaluation_interval: int | None,
    evaluation_confidence_threshold: float | None,
    evaluation_nms_threshold: float | None,
    learning_rate: float,
    weight_decay: float,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    min_lr_ratio: float,
    grad_clip_norm: float,
    metrics_history: list[dict[str, object]],
    validation_history: list[dict[str, object]],
    evaluated_epochs: tuple[int, ...],
    warm_start_summary: dict[str, object],
    implementation_mode: str,
    augmentation_options: dict[str, object] | None,
    best_metric_name: str,
    best_metric_value: float | None,
    best_checkpoint_state: dict[str, object] | None,
) -> dict[str, object]:
    """构建 YOLO11 detection 可恢复 checkpoint state。"""

    checkpoint_state: dict[str, object] = {
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict(),
        "scaler_state_dict": scaler.state_dict(),
        "model_type": model_type,
        "model_scale": model_scale,
        "category_names": list(category_names),
        "input_size": list(input_size),
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "epoch": epoch,
        "precision": precision,
        "validation_split_name": validation_split_name,
        "evaluation_interval": evaluation_interval,
        "evaluation_confidence_threshold": evaluation_confidence_threshold,
        "evaluation_nms_threshold": evaluation_nms_threshold,
        "learning_rate": learning_rate,
        "weight_decay": weight_decay,
        "class_loss_weight": class_loss_weight,
        "box_loss_weight": box_loss_weight,
        "dfl_loss_weight": dfl_loss_weight,
        "assign_topk": assign_topk,
        "assign_alpha": assign_alpha,
        "assign_beta": assign_beta,
        "min_lr_ratio": min_lr_ratio,
        "grad_clip_norm": grad_clip_norm,
        "metrics_history": metrics_history,
        "validation_history": validation_history,
        "evaluated_epochs": list(evaluated_epochs),
        "warm_start": warm_start_summary,
        "implementation_mode": implementation_mode,
        "augmentation": dict(augmentation_options or {}),
        "best_metric_name": best_metric_name,
        "best_metric_value": best_metric_value,
        "best_checkpoint_state": best_checkpoint_state,
    }
    if ema_model is not None:
        checkpoint_state["ema_state_dict"] = ema_model.state_dict()
        checkpoint_state["ema_updates"] = max(0, int(ema_updates or 0))
    return checkpoint_state


def encode_yolo11_detection_checkpoint_state(
    *,
    torch_module: Any,
    checkpoint_state: dict[str, object] | None,
) -> bytes:
    """把 YOLO11 detection checkpoint state 编码为 bytes。"""

    if checkpoint_state is None:
        return b""
    buffer = io.BytesIO()
    torch_module.save(checkpoint_state, buffer)
    return buffer.getvalue()


def decode_yolo11_detection_checkpoint_state(
    *,
    torch_module: Any,
    checkpoint_bytes: bytes,
) -> dict[str, object]:
    """从 bytes 解码 YOLO11 detection checkpoint state。"""

    payload = torch_module.load(io.BytesIO(checkpoint_bytes), map_location="cpu")
    if not isinstance(payload, dict):
        raise InvalidRequestError("checkpoint 内容不合法")
    return dict(payload)


def build_yolo11_detection_epoch_checkpoint_update(
    *,
    torch_module: Any,
    model: Any,
    ema_model: Any | None,
    ema_updates: int | None,
    optimizer: Any,
    scheduler: Any,
    scaler: Any,
    model_type: str,
    model_scale: str,
    category_names: tuple[str, ...],
    input_size: tuple[int, int],
    batch_size: int,
    max_epochs: int,
    epoch: int,
    precision: str,
    validation_split_name: str | None,
    evaluation_interval: int | None,
    evaluation_confidence_threshold: float | None,
    evaluation_nms_threshold: float | None,
    learning_rate: float,
    weight_decay: float,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    min_lr_ratio: float,
    grad_clip_norm: float,
    metrics_history: list[dict[str, object]],
    validation_history: list[dict[str, object]],
    evaluated_epochs: tuple[int, ...],
    warm_start_summary: dict[str, object],
    implementation_mode: str,
    augmentation_options: dict[str, object] | None,
    best_metric_name: str,
    candidate_best_metric_value: float,
    previous_best_checkpoint_bytes: bytes,
    improved_best: bool,
) -> Yolo11DetectionEpochCheckpointUpdate:
    """构建 YOLO11 detection 一个 epoch 后的 latest / best checkpoint bytes。"""

    previous_best_checkpoint_state = (
        decode_yolo11_detection_checkpoint_state(
            torch_module=torch_module,
            checkpoint_bytes=previous_best_checkpoint_bytes,
        )
        if previous_best_checkpoint_bytes
        else None
    )
    current_checkpoint_state = build_yolo11_detection_checkpoint_state(
        model=model,
        ema_model=ema_model,
        ema_updates=ema_updates,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        model_type=model_type,
        model_scale=model_scale,
        category_names=category_names,
        input_size=input_size,
        batch_size=batch_size,
        max_epochs=max_epochs,
        epoch=epoch,
        precision=precision,
        validation_split_name=validation_split_name,
        evaluation_interval=evaluation_interval,
        evaluation_confidence_threshold=evaluation_confidence_threshold,
        evaluation_nms_threshold=evaluation_nms_threshold,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        class_loss_weight=class_loss_weight,
        box_loss_weight=box_loss_weight,
        dfl_loss_weight=dfl_loss_weight,
        assign_topk=assign_topk,
        assign_alpha=assign_alpha,
        assign_beta=assign_beta,
        min_lr_ratio=min_lr_ratio,
        grad_clip_norm=grad_clip_norm,
        metrics_history=metrics_history,
        validation_history=validation_history,
        evaluated_epochs=evaluated_epochs,
        warm_start_summary=warm_start_summary,
        implementation_mode=implementation_mode,
        augmentation_options=augmentation_options,
        best_metric_name=best_metric_name,
        best_metric_value=candidate_best_metric_value,
        best_checkpoint_state=previous_best_checkpoint_state,
    )
    best_checkpoint_bytes = previous_best_checkpoint_bytes
    best_metric_value = candidate_best_metric_value
    if improved_best:
        current_best_checkpoint_state = dict(current_checkpoint_state)
        current_best_checkpoint_state["best_checkpoint_state"] = None
        current_checkpoint_state["best_checkpoint_state"] = (
            current_best_checkpoint_state
        )
        best_checkpoint_bytes = encode_yolo11_detection_checkpoint_state(
            torch_module=torch_module,
            checkpoint_state=current_best_checkpoint_state,
        )

    latest_checkpoint_bytes = encode_yolo11_detection_checkpoint_state(
        torch_module=torch_module,
        checkpoint_state=current_checkpoint_state,
    )
    return Yolo11DetectionEpochCheckpointUpdate(
        latest_checkpoint_bytes=latest_checkpoint_bytes,
        best_checkpoint_bytes=best_checkpoint_bytes,
        best_metric_value=best_metric_value,
    )


__all__ = [
    "Yolo11DetectionEpochCheckpointUpdate",
    "build_yolo11_detection_checkpoint_state",
    "build_yolo11_detection_epoch_checkpoint_update",
    "decode_yolo11_detection_checkpoint_state",
    "encode_yolo11_detection_checkpoint_state",
]
