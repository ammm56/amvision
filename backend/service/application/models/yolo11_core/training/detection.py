"""YOLO11 detection 训练执行辅助入口。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo11_core.losses import (
    compute_yolo11_detection_loss,
)


def is_yolo11_detection_core_model(model: Any) -> bool:
    """判断当前模型是否是 YOLO11 detection core 构建结果。"""

    model_name = str(getattr(model, "model_name", ""))
    model_module = str(model.__class__.__module__)
    return model_name.startswith("yolo11-") and "yolo11_core.nn.model" in model_module


def compute_yolo11_detection_training_loss(
    *,
    torch_module: Any,
    model: Any,
    raw_outputs: dict[str, Any],
    batch_targets: tuple[Any, ...],
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    assign_topk2: int | None = None,
) -> dict[str, Any]:
    """按 YOLO11 detection core 规则计算训练损失。"""

    detect_head = model.model[-1]
    return compute_yolo11_detection_loss(
        torch_module=torch_module,
        detect_head=detect_head,
        raw_outputs=raw_outputs,
        batch_targets=batch_targets,
        class_loss_weight=class_loss_weight,
        box_loss_weight=box_loss_weight,
        dfl_loss_weight=dfl_loss_weight,
        assign_topk=assign_topk,
        assign_alpha=assign_alpha,
        assign_beta=assign_beta,
        assign_topk2=assign_topk2,
    )
