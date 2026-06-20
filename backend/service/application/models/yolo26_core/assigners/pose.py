"""YOLO26 pose target assigner。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo26_core.assigners.detection import (
    assign_yolo26_detection_targets,
    yolo26_box_iou_aligned,
)


def assign_yolo26_pose_targets(
    *,
    torch_module: Any,
    pred_boxes: Any,
    class_probabilities: Any,
    anchor_centers_xy: Any,
    gt_boxes: Any,
    gt_classes: Any,
    topk: int,
    alpha: float,
    beta: float,
    topk2: int | None = None,
) -> dict[str, Any]:
    """按 YOLO26 pose 的 TaskAlignedAssigner 规则分配正样本。"""

    return assign_yolo26_detection_targets(
        torch_module=torch_module,
        pred_boxes=pred_boxes,
        class_probabilities=class_probabilities,
        anchor_centers_xy=anchor_centers_xy,
        gt_boxes=gt_boxes,
        gt_classes=gt_classes,
        topk=topk,
        alpha=alpha,
        beta=beta,
        topk2=topk2,
    )


def yolo26_pose_box_iou_aligned(
    *,
    torch_module: Any,
    boxes1: Any,
    boxes2: Any,
) -> Any:
    """计算 YOLO26 pose 一一对应 bbox CIoU。"""

    return yolo26_box_iou_aligned(
        torch_module=torch_module,
        boxes1=boxes1,
        boxes2=boxes2,
    )


__all__ = [
    "assign_yolo26_pose_targets",
    "yolo26_pose_box_iou_aligned",
]
