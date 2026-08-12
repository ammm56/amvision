"""YOLO11 segmentation loss。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.losses.segmentation import (
    YoloSegmentationDetectionLossTerms,
    compute_yolo_segmentation_mask_loss as compute_yolo11_segmentation_mask_loss,
    crop_yolo_segmentation_mask_loss as crop_yolo11_segmentation_mask_loss,
    finalize_yolo_segmentation_detection_loss_terms,
)

from backend.service.application.models.yolo11_core.assigners.detection import (
    yolo11_box_iou_aligned,
)
from backend.service.application.models.yolo11_core.losses.detection import (
    yolo11_distribution_focal_loss,
)
from backend.service.application.models.yolo11_core.targets import (
    yolo11_bbox_xyxy_to_distances,
)


def compute_yolo11_segmentation_detection_loss(
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
    """计算 YOLO11 segmentation head 的分类、bbox 和 DFL 损失。"""

    terms = compute_yolo11_segmentation_detection_loss_terms(
        torch_module=torch_module,
        prediction=prediction,
        assignment=assignment,
        anchor_points=anchor_points,
        stride_tensor=stride_tensor,
        dfl_weight=dfl_weight,
        num_classes=num_classes,
        distance_logits=distance_logits,
        reg_max=reg_max,
    )
    return finalize_yolo_segmentation_detection_loss_terms(
        torch_module=torch_module,
        terms=[terms],
        batch_size=1,
    )


def compute_yolo11_segmentation_detection_loss_terms(
    *,
    torch_module: Any,
    prediction: Any,
    assignment: Any | None,
    anchor_points: Any,
    stride_tensor: Any,
    dfl_weight: float,
    num_classes: int,
    distance_logits: Any | None = None,
    reg_max: int | None = None,
) -> YoloSegmentationDetectionLossTerms:
    """返回单图未归一化 loss，供全 batch 统一归一化。"""

    _ = dfl_weight
    foreground_mask = (
        assignment.fg_mask.to(prediction.device).bool()
        if assignment is not None
        else torch_module.zeros(
            int(prediction.shape[0]),
            dtype=torch_module.bool,
            device=prediction.device,
        )
    )
    foreground_count = int(foreground_mask.sum().item())
    zero_loss = prediction.new_zeros(())

    class_scores = prediction[:, 4 : 4 + int(num_classes)]
    class_targets = torch_module.zeros_like(class_scores, device=prediction.device)
    target_scores = (
        assignment.box_scores.to(device=prediction.device, dtype=prediction.dtype)
        if assignment is not None
        else prediction.new_zeros((int(prediction.shape[0]),))
    )
    if foreground_count > 0:
        class_targets[
            foreground_mask,
            assignment.class_ids.to(prediction.device)[foreground_mask],
        ] = target_scores[foreground_mask]
    target_score_sum = target_scores.sum()
    class_loss_full = torch_module.nn.BCEWithLogitsLoss(reduction="none")(
        class_scores,
        class_targets,
    )
    class_loss_sum = class_loss_full.sum()
    if foreground_count <= 0:
        return YoloSegmentationDetectionLossTerms(
            class_loss_sum,
            zero_loss,
            zero_loss,
            target_score_sum,
        )

    pred_boxes = decode_yolo11_segmentation_training_boxes(
        torch_module=torch_module,
        prediction=prediction,
        anchor_points=anchor_points,
        stride_tensor=stride_tensor,
    )
    target_boxes = assignment.box_targets.to(prediction.device)
    foreground_stride = stride_tensor[foreground_mask].view(-1, 1)
    iou = yolo11_box_iou_aligned(
        torch_module=torch_module,
        boxes1=pred_boxes[foreground_mask] / foreground_stride,
        boxes2=target_boxes[foreground_mask] / foreground_stride,
    )
    foreground_scores = target_scores[foreground_mask]
    box_loss_sum = (
        ((1.0 - iou) * foreground_scores).sum()
        if int(iou.numel()) > 0
        else zero_loss
    )
    dfl_loss_sum = prediction.new_zeros(())
    if distance_logits is not None and reg_max is not None:
        target_distances = yolo11_bbox_xyxy_to_distances(
            torch_module=torch_module,
            boxes_xyxy=target_boxes[foreground_mask],
            anchor_points=anchor_points[foreground_mask],
            stride_tensor=stride_tensor[foreground_mask],
            reg_max=int(reg_max),
        )
        if int(reg_max) > 1:
            foreground_distance_logits = distance_logits[foreground_mask].view(
                -1, 4, int(reg_max)
            )
            raw_dfl_loss = yolo11_distribution_focal_loss(
                torch_module=torch_module,
                logits=foreground_distance_logits,
                target=target_distances,
            )
            dfl_loss_sum = (raw_dfl_loss * foreground_scores).sum()
        else:
            foreground_distance_logits = distance_logits[foreground_mask].view(-1, 4)
            raw_dfl_loss = torch_module.nn.functional.smooth_l1_loss(
                torch_module.nn.functional.softplus(foreground_distance_logits),
                target_distances,
                reduction="none",
            )
            dfl_loss_sum = (raw_dfl_loss.mean(dim=1) * foreground_scores).sum()
    return YoloSegmentationDetectionLossTerms(
        class_loss_sum,
        box_loss_sum,
        dfl_loss_sum,
        target_score_sum,
    )


def decode_yolo11_segmentation_training_boxes(
    *,
    torch_module: Any,
    prediction: Any,
    anchor_points: Any,
    stride_tensor: Any,
) -> Any:
    """按 YOLO11 segmentation 训练坐标系把 ltrb 距离解码成像素级 xyxy。"""

    distances = prediction[:, :4]
    left_top = distances[:, :2]
    right_bottom = distances[:, 2:4]
    anchors = anchor_points.to(device=prediction.device, dtype=prediction.dtype)
    stride = stride_tensor.to(device=prediction.device, dtype=prediction.dtype)
    boxes = torch_module.cat((anchors - left_top, anchors + right_bottom), dim=-1)
    return boxes * stride.repeat(1, 4)


__all__ = [
    "compute_yolo11_segmentation_detection_loss",
    "compute_yolo11_segmentation_detection_loss_terms",
    "compute_yolo11_segmentation_mask_loss",
    "crop_yolo11_segmentation_mask_loss",
    "decode_yolo11_segmentation_training_boxes",
]
