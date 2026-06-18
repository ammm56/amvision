"""YOLOv8 pose target assigner。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolov8_core.assigners.detection import (
    assign_yolov8_detection_targets,
    yolov8_box_iou_aligned,
)


def assign_yolov8_pose_targets(
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
) -> dict[str, Any]:
    """按 YOLOv8 pose 的 TAL 规则分配正样本。"""

    return assign_yolov8_detection_targets(
        torch_module=torch_module,
        pred_boxes=pred_boxes,
        class_probabilities=class_probabilities,
        anchor_centers_xy=anchor_centers_xy,
        gt_boxes=gt_boxes,
        gt_classes=gt_classes,
        topk=topk,
        alpha=alpha,
        beta=beta,
    )


def yolov8_pose_box_iou_aligned(
    *,
    torch_module: Any,
    boxes1: Any,
    boxes2: Any,
) -> Any:
    """计算 YOLOv8 pose 一一对应 bbox IoU。"""

    return yolov8_box_iou_aligned(
        torch_module=torch_module,
        boxes1=boxes1,
        boxes2=boxes2,
    )


__all__ = [
    "assign_yolov8_pose_targets",
    "yolov8_pose_box_iou_aligned",
]
