"""YOLOv8 segmentation loss。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.losses.segmentation import (
    compute_yolo_segmentation_mask_loss as compute_yolov8_segmentation_mask_loss,
    crop_yolo_segmentation_mask_loss as crop_yolov8_segmentation_mask_loss,
)

from backend.service.application.models.yolov8_core.assigners.detection import (
    yolov8_box_iou_aligned,
)
from backend.service.application.models.yolov8_core.losses.detection import (
    yolov8_distribution_focal_loss,
)
from backend.service.application.models.yolov8_core.targets import (
    yolov8_bbox_xyxy_to_distances,
)


def compute_yolov8_segmentation_detection_loss(
    *,
    torch_module: Any,
    prediction: Any,
    assignment: Any,
    anchor_points: Any,
    stride_tensor: Any,
    dfl_weight: float,
    num_classes: int,
    distance_logits: Any | None = None,
    reg_max: int | None = None,
) -> tuple[Any, Any, Any]:
    """计算 YOLOv8 segmentation head 的分类、bbox 和 DFL 损失。"""

    _ = dfl_weight
    foreground_mask = assignment.fg_mask.to(prediction.device).bool()
    foreground_count = int(foreground_mask.sum().item())
    zero_loss = prediction.new_zeros(())

    class_scores = prediction[:, 4 : 4 + int(num_classes)]
    class_targets = torch_module.zeros_like(class_scores, device=prediction.device)
    target_scores = assignment.box_scores.to(device=prediction.device, dtype=prediction.dtype)
    if foreground_count > 0:
        class_targets[
            foreground_mask,
            assignment.class_ids.to(prediction.device)[foreground_mask],
        ] = target_scores[foreground_mask]
    target_score_sum = target_scores.sum().clamp_min(1.0)
    class_loss_full = torch_module.nn.BCEWithLogitsLoss(reduction="none")(
        class_scores,
        class_targets,
    )
    class_loss = class_loss_full.sum() / target_score_sum
    if foreground_count <= 0:
        return class_loss, zero_loss, zero_loss

    pred_boxes = decode_yolov8_segmentation_training_boxes(
        torch_module=torch_module,
        prediction=prediction,
        anchor_points=anchor_points,
        stride_tensor=stride_tensor,
    )
    target_boxes = assignment.box_targets.to(prediction.device)
    foreground_stride = stride_tensor[foreground_mask].view(-1, 1)
    iou = yolov8_box_iou_aligned(
        torch_module=torch_module,
        boxes1=pred_boxes[foreground_mask] / foreground_stride,
        boxes2=target_boxes[foreground_mask] / foreground_stride,
    )
    foreground_scores = target_scores[foreground_mask]
    box_loss = (
        ((1.0 - iou) * foreground_scores).sum() / target_score_sum
        if int(iou.numel()) > 0
        else zero_loss
    )
    dfl_loss = prediction.new_zeros(())
    if distance_logits is not None and reg_max is not None:
        target_distances = yolov8_bbox_xyxy_to_distances(
            torch_module=torch_module,
            boxes_xyxy=target_boxes[foreground_mask],
            anchor_points=anchor_points[foreground_mask],
            stride_tensor=stride_tensor[foreground_mask],
            reg_max=int(reg_max),
        )
        if int(reg_max) > 1:
            foreground_distance_logits = distance_logits[foreground_mask].view(-1, 4, int(reg_max))
            raw_dfl_loss = yolov8_distribution_focal_loss(
                torch_module=torch_module,
                logits=foreground_distance_logits,
                target=target_distances,
            )
            dfl_loss = (raw_dfl_loss * foreground_scores).sum() / target_score_sum
        else:
            foreground_distance_logits = distance_logits[foreground_mask].view(-1, 4)
            raw_dfl_loss = torch_module.nn.functional.smooth_l1_loss(
                torch_module.nn.functional.softplus(foreground_distance_logits),
                target_distances,
                reduction="none",
            )
            dfl_loss = (raw_dfl_loss.mean(dim=1) * foreground_scores).sum() / target_score_sum
    return class_loss, box_loss, dfl_loss


def decode_yolov8_segmentation_training_boxes(
    *,
    torch_module: Any,
    prediction: Any,
    anchor_points: Any,
    stride_tensor: Any,
) -> Any:
    """按 YOLOv8 segmentation 训练坐标系把 ltrb 距离解码成像素级 xyxy。"""

    distances = prediction[:, :4]
    left_top = distances[:, :2]
    right_bottom = distances[:, 2:4]
    anchors = anchor_points.to(device=prediction.device, dtype=prediction.dtype)
    stride = stride_tensor.to(device=prediction.device, dtype=prediction.dtype)
    boxes = torch_module.cat((anchors - left_top, anchors + right_bottom), dim=-1)
    return boxes * stride.repeat(1, 4)


__all__ = [
    "compute_yolov8_segmentation_detection_loss",
    "compute_yolov8_segmentation_mask_loss",
    "crop_yolov8_segmentation_mask_loss",
    "decode_yolov8_segmentation_training_boxes",
]
