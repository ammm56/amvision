"""YOLO26 pose checkpoint 与 resume 规则。"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class Yolo26PoseResumeState:
    """描述 YOLO26 pose resume checkpoint 内容。"""

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
    saved_kpt_loss_weight: float
    saved_assign_topk: int
    saved_assign_alpha: float
    saved_assign_beta: float
    saved_grad_clip_norm: float
    saved_evaluation_confidence_threshold: float
    saved_evaluation_nms_threshold: float
    saved_keypoint_confidence_threshold: float


def load_yolo26_pose_resume_state(
    *,
    checkpoint_path: Path,
    torch_module: Any,
) -> Yolo26PoseResumeState:
    """读取 YOLO26 pose resume checkpoint。"""

    checkpoint = torch_module.load(
        str(checkpoint_path),
        map_location="cpu",
        weights_only=False,
    )
    if not isinstance(checkpoint, dict):
        raise InvalidRequestError("YOLO26 pose checkpoint 内容不合法")
    return Yolo26PoseResumeState(
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
        saved_evaluation_interval=int(checkpoint.get("saved_eval_interval", 0)),
        saved_min_lr_ratio=float(checkpoint.get("saved_min_lr", 0)),
        saved_class_loss_weight=float(checkpoint.get("saved_class_loss_weight", 0)),
        saved_box_loss_weight=float(checkpoint.get("saved_box_loss_weight", 0)),
        saved_dfl_loss_weight=float(checkpoint.get("saved_dfl_loss_weight", 0)),
        saved_kpt_loss_weight=float(checkpoint.get("saved_kpt_loss_weight", 0)),
        saved_assign_topk=int(checkpoint.get("saved_assign_topk", 0)),
        saved_assign_alpha=float(checkpoint.get("saved_assign_alpha", 0)),
        saved_assign_beta=float(checkpoint.get("saved_assign_beta", 0)),
        saved_grad_clip_norm=float(checkpoint.get("saved_grad_clip", 0)),
        saved_evaluation_confidence_threshold=float(
            checkpoint.get("saved_eval_conf", 0)
        ),
        saved_evaluation_nms_threshold=float(checkpoint.get("saved_eval_nms", 0)),
        saved_keypoint_confidence_threshold=float(checkpoint.get("saved_kpt_conf", 0)),
    )


def validate_yolo26_pose_resume_parameters(
    state: Yolo26PoseResumeState,
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
    kpt_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    grad_clip_norm: float,
    evaluation_confidence_threshold: float,
    evaluation_nms_threshold: float,
    keypoint_confidence_threshold: float,
) -> None:
    """校验 YOLO26 pose resume 参数是否匹配当前请求。"""

    checks = {
        "batch_size": state.saved_batch_size == batch_size,
        "max_epochs": state.saved_max_epochs == max_epochs,
        "evaluation_interval": state.saved_evaluation_interval == evaluation_interval,
        "assign_topk": state.saved_assign_topk == assign_topk,
        "learning_rate": abs(state.saved_learning_rate - learning_rate) <= 1e-8,
        "weight_decay": abs(state.saved_weight_decay - weight_decay) <= 1e-8,
        "min_lr_ratio": abs(state.saved_min_lr_ratio - min_lr_ratio) <= 1e-8,
        "class_loss_weight": abs(state.saved_class_loss_weight - class_loss_weight)
        <= 1e-8,
        "box_loss_weight": abs(state.saved_box_loss_weight - box_loss_weight) <= 1e-8,
        "dfl_loss_weight": abs(state.saved_dfl_loss_weight - dfl_loss_weight) <= 1e-8,
        "kpt_loss_weight": abs(state.saved_kpt_loss_weight - kpt_loss_weight) <= 1e-8,
        "assign_alpha": abs(state.saved_assign_alpha - assign_alpha) <= 1e-8,
        "assign_beta": abs(state.saved_assign_beta - assign_beta) <= 1e-8,
        "grad_clip_norm": abs(state.saved_grad_clip_norm - grad_clip_norm) <= 1e-8,
        "evaluation_confidence_threshold": (
            abs(
                state.saved_evaluation_confidence_threshold
                - evaluation_confidence_threshold
            )
            <= 1e-8
        ),
        "evaluation_nms_threshold": (
            abs(state.saved_evaluation_nms_threshold - evaluation_nms_threshold) <= 1e-8
        ),
        "keypoint_confidence_threshold": (
            abs(
                state.saved_keypoint_confidence_threshold
                - keypoint_confidence_threshold
            )
            <= 1e-8
        ),
    }
    mismatches = [name for name, matched in checks.items() if not matched]
    if mismatches:
        raise InvalidRequestError(
            "YOLO26 pose resume 参数与 checkpoint 记录不一致",
            details={"mismatches": mismatches},
        )


def restore_yolo26_pose_training_state(
    *,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any | None,
    state: Yolo26PoseResumeState,
    device_name: str,
) -> None:
    """恢复 YOLO26 pose 模型、optimizer、scheduler 和 scaler 状态。"""

    _load_yolo26_pose_model_state(model=model, state_dict=state.model_state_dict)
    optimizer.load_state_dict(state.optimizer_state_dict)
    _move_optimizer_state_to_device(optimizer=optimizer, device_name=device_name)
    if state.scheduler_state_dict is not None:
        scheduler.load_state_dict(state.scheduler_state_dict)
    if state.scaler_state_dict is not None and scaler is not None:
        scaler.load_state_dict(state.scaler_state_dict)


def build_yolo26_pose_checkpoint_bytes(
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
    kpt_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    grad_clip_norm: float,
    evaluation_confidence_threshold: float,
    evaluation_nms_threshold: float,
    keypoint_confidence_threshold: float,
    torch_module: Any,
) -> bytes:
    """把 YOLO26 pose 训练状态编码为 checkpoint bytes。"""

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
        "saved_lr": learning_rate,
        "saved_wd": weight_decay,
        "saved_eval_interval": evaluation_interval,
        "saved_min_lr": min_lr_ratio,
        "saved_class_loss_weight": class_loss_weight,
        "saved_box_loss_weight": box_loss_weight,
        "saved_dfl_loss_weight": dfl_loss_weight,
        "saved_kpt_loss_weight": kpt_loss_weight,
        "saved_assign_topk": assign_topk,
        "saved_assign_alpha": assign_alpha,
        "saved_assign_beta": assign_beta,
        "saved_grad_clip": grad_clip_norm,
        "saved_eval_conf": evaluation_confidence_threshold,
        "saved_eval_nms": evaluation_nms_threshold,
        "saved_kpt_conf": keypoint_confidence_threshold,
        "model_type": "yolo26",
        "task_type": "pose",
    }
    buffer = io.BytesIO()
    torch_module.save(payload, buffer)
    return buffer.getvalue()


def _load_yolo26_pose_model_state(*, model: Any, state_dict: dict[str, object]) -> None:
    """加载 checkpoint 中 shape 匹配的 YOLO26 pose 权重。"""

    filtered = {}
    model_state = model.state_dict()
    for key, value in state_dict.items():
        parameter = model_state.get(key)
        if parameter is not None and parameter.shape == value.shape:
            filtered[key] = value
    model.load_state_dict(filtered, strict=False)


def _move_optimizer_state_to_device(*, optimizer: Any, device_name: str) -> None:
    """把 optimizer state 移到训练设备。"""

    if "cuda" not in device_name:
        return
    for state_payload in optimizer.state.values():
        for key, value in state_payload.items():
            if hasattr(value, "to") and hasattr(value, "device"):
                try:
                    state_payload[key] = value.to(device_name)
                except Exception:
                    pass


__all__ = [
    "Yolo26PoseResumeState",
    "build_yolo26_pose_checkpoint_bytes",
    "load_yolo26_pose_resume_state",
    "restore_yolo26_pose_training_state",
    "validate_yolo26_pose_resume_parameters",
]
