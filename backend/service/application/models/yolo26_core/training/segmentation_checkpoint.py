"""YOLO26 segmentation checkpoint 与 resume 规则。"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class Yolo26SegmentationResumeState:
    """描述 YOLO26 segmentation resume checkpoint 内容。"""

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
    saved_batch_size: int
    saved_max_epochs: int
    saved_learning_rate: float
    saved_weight_decay: float
    saved_evaluation_interval: int
    saved_min_lr_ratio: float
    saved_class_loss_weight: float
    saved_box_loss_weight: float
    saved_dfl_loss_weight: float
    saved_mask_loss_weight: float
    saved_assign_topk: int
    saved_assign_alpha: float
    saved_assign_beta: float
    saved_grad_clip_norm: float
    saved_evaluation_confidence_threshold: float
    saved_evaluation_nms_threshold: float


def load_yolo26_segmentation_resume_state(
    *,
    checkpoint_path: Path,
    torch_module: Any,
) -> Yolo26SegmentationResumeState:
    """读取 YOLO26 segmentation resume checkpoint。"""

    checkpoint = torch_module.load(
        str(checkpoint_path),
        map_location="cpu",
        weights_only=False,
    )
    if not isinstance(checkpoint, dict):
        raise InvalidRequestError("YOLO26 segmentation checkpoint 内容不合法")
    return Yolo26SegmentationResumeState(
        model_state_dict=checkpoint.get("model_state_dict", {}),
        optimizer_state_dict=checkpoint.get("optimizer_state_dict", {}),
        scheduler_state_dict=checkpoint.get("scheduler_state_dict"),
        scaler_state_dict=checkpoint.get("scaler_state_dict"),
        metrics_history=checkpoint.get("metrics_history", []),
        validation_history=checkpoint.get("validation_history", []),
        best_metric_value=float(checkpoint.get("best_metric_value", 0)),
        best_metric_name=str(checkpoint.get("best_metric_name", "val_map50_95")),
        epoch=int(checkpoint.get("epoch", 0)),
        global_iteration=int(checkpoint.get("global_iteration", 0)),
        saved_batch_size=int(checkpoint.get("saved_batch_size", 0)),
        saved_max_epochs=int(checkpoint.get("saved_max_epochs", 0)),
        saved_learning_rate=float(checkpoint.get("saved_lr", 0)),
        saved_weight_decay=float(checkpoint.get("saved_wd", 0)),
        saved_evaluation_interval=int(
            checkpoint.get("saved_evaluation_interval", 0)
        ),
        saved_min_lr_ratio=float(checkpoint.get("saved_min_lr", 0)),
        saved_class_loss_weight=float(checkpoint.get("saved_class_loss_weight", 0)),
        saved_box_loss_weight=float(checkpoint.get("saved_box_loss_weight", 0)),
        saved_dfl_loss_weight=float(checkpoint.get("saved_dfl_loss_weight", 0)),
        saved_mask_loss_weight=float(checkpoint.get("saved_mask_loss_weight", 0)),
        saved_assign_topk=int(checkpoint.get("saved_assign_topk", 0)),
        saved_assign_alpha=float(checkpoint.get("saved_assign_alpha", 0)),
        saved_assign_beta=float(checkpoint.get("saved_assign_beta", 0)),
        saved_grad_clip_norm=float(checkpoint.get("saved_grad_clip", 0)),
        saved_evaluation_confidence_threshold=float(
            checkpoint.get("saved_evaluation_confidence_threshold", 0)
        ),
        saved_evaluation_nms_threshold=float(
            checkpoint.get("saved_evaluation_nms_threshold", 0)
        ),
    )


def validate_yolo26_segmentation_resume_parameters(
    state: Yolo26SegmentationResumeState,
    *,
    batch_size: int,
    max_epochs: int,
    learning_rate: float,
    weight_decay: float,
    evaluation_interval: int,
    min_lr_ratio: float,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    mask_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    grad_clip_norm: float,
    evaluation_confidence_threshold: float,
    evaluation_nms_threshold: float,
) -> None:
    """校验 resume checkpoint 记录的训练参数是否匹配当前请求。"""

    mismatches = []
    if state.saved_batch_size != batch_size:
        mismatches.append("batch_size")
    if state.saved_max_epochs != max_epochs:
        mismatches.append("max_epochs")
    if abs(state.saved_learning_rate - learning_rate) > 1e-8:
        mismatches.append("learning_rate")
    if abs(state.saved_weight_decay - weight_decay) > 1e-8:
        mismatches.append("weight_decay")
    if state.saved_evaluation_interval != evaluation_interval:
        mismatches.append("evaluation_interval")
    if abs(state.saved_min_lr_ratio - min_lr_ratio) > 1e-8:
        mismatches.append("min_lr_ratio")
    if abs(state.saved_class_loss_weight - class_loss_weight) > 1e-8:
        mismatches.append("class_loss_weight")
    if abs(state.saved_box_loss_weight - box_loss_weight) > 1e-8:
        mismatches.append("box_loss_weight")
    if abs(state.saved_dfl_loss_weight - dfl_loss_weight) > 1e-8:
        mismatches.append("dfl_loss_weight")
    if abs(state.saved_mask_loss_weight - mask_loss_weight) > 1e-8:
        mismatches.append("mask_loss_weight")
    if state.saved_assign_topk != assign_topk:
        mismatches.append("assign_topk")
    if abs(state.saved_assign_alpha - assign_alpha) > 1e-8:
        mismatches.append("assign_alpha")
    if abs(state.saved_assign_beta - assign_beta) > 1e-8:
        mismatches.append("assign_beta")
    if abs(state.saved_grad_clip_norm - grad_clip_norm) > 1e-8:
        mismatches.append("grad_clip_norm")
    if (
        abs(
            state.saved_evaluation_confidence_threshold
            - evaluation_confidence_threshold
        )
        > 1e-8
    ):
        mismatches.append("evaluation_confidence_threshold")
    if abs(state.saved_evaluation_nms_threshold - evaluation_nms_threshold) > 1e-8:
        mismatches.append("evaluation_nms_threshold")
    if mismatches:
        raise InvalidRequestError(
            "YOLO26 segmentation resume 参数与 checkpoint 记录不一致",
            details={"mismatches": mismatches},
        )


def load_yolo26_segmentation_model_state(
    *,
    model: Any,
    state_dict: dict[str, object],
) -> None:
    """把 checkpoint 里的可匹配权重加载进 YOLO26 segmentation 模型。"""

    filtered = {}
    for key, value in state_dict.items():
        parameter = model.state_dict().get(key)
        if parameter is not None and parameter.shape == value.shape:
            filtered[key] = value
    model.load_state_dict(filtered, strict=False)


def restore_yolo26_segmentation_training_state(
    *,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any | None,
    state: Yolo26SegmentationResumeState,
    device_name: str,
) -> None:
    """恢复 YOLO26 segmentation 模型、optimizer、scheduler 和 scaler 状态。"""

    load_yolo26_segmentation_model_state(
        model=model,
        state_dict=state.model_state_dict,
    )
    optimizer.load_state_dict(state.optimizer_state_dict)
    _move_yolo26_segmentation_optimizer_state_to_device(
        optimizer=optimizer,
        device_name=device_name,
    )
    if state.scheduler_state_dict is not None and scheduler is not None:
        scheduler.load_state_dict(state.scheduler_state_dict)
    if state.scaler_state_dict is not None and scaler is not None:
        scaler.load_state_dict(state.scaler_state_dict)


def _move_yolo26_segmentation_optimizer_state_to_device(
    *,
    optimizer: Any,
    device_name: str,
) -> None:
    """把 YOLO26 segmentation optimizer state 移到训练设备。"""

    if "cuda" not in device_name:
        return
    for state_payload in optimizer.state.values():
        for key, value in state_payload.items():
            if hasattr(value, "to") and hasattr(value, "device"):
                try:
                    state_payload[key] = value.to(device_name)
                except Exception:
                    pass


def build_yolo26_segmentation_checkpoint_bytes(
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
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    mask_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    grad_clip_norm: float,
    evaluation_confidence_threshold: float,
    evaluation_nms_threshold: float,
    torch_module: Any,
) -> bytes:
    """把 YOLO26 segmentation 训练状态编码为 checkpoint bytes。"""

    payload = {
        "epoch": epoch + 1,
        "global_iteration": global_iteration,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict() if scheduler else None,
        "scaler_state_dict": scaler.state_dict() if scaler else None,
        "metrics_history": metrics_history,
        "validation_history": validation_history,
        "best_metric_value": best_metric_value,
        "best_metric_name": best_metric_name,
        "saved_batch_size": batch_size,
        "saved_max_epochs": max_epochs,
        "saved_lr": learning_rate,
        "saved_wd": weight_decay,
        "saved_evaluation_interval": evaluation_interval,
        "saved_min_lr": min_lr_ratio,
        "saved_class_loss_weight": class_loss_weight,
        "saved_box_loss_weight": box_loss_weight,
        "saved_dfl_loss_weight": dfl_loss_weight,
        "saved_mask_loss_weight": mask_loss_weight,
        "saved_assign_topk": assign_topk,
        "saved_assign_alpha": assign_alpha,
        "saved_assign_beta": assign_beta,
        "saved_grad_clip": grad_clip_norm,
        "saved_evaluation_confidence_threshold": evaluation_confidence_threshold,
        "saved_evaluation_nms_threshold": evaluation_nms_threshold,
        "model_type": "yolo26",
        "task_type": "segmentation",
    }
    buffer = io.BytesIO()
    torch_module.save(payload, buffer)
    return buffer.getvalue()


__all__ = [
    "Yolo26SegmentationResumeState",
    "build_yolo26_segmentation_checkpoint_bytes",
    "load_yolo26_segmentation_model_state",
    "load_yolo26_segmentation_resume_state",
    "restore_yolo26_segmentation_training_state",
    "validate_yolo26_segmentation_resume_parameters",
]
