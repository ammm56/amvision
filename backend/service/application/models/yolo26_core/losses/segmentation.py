"""YOLO26 segmentation loss。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo26_core.assigners.detection import (
    yolo26_box_iou_aligned,
)
from backend.service.application.models.yolo26_core.losses.detection import (
    yolo26_distribution_focal_loss,
)
from backend.service.application.models.yolo26_core.targets import (
    yolo26_bbox_xyxy_to_distances,
)


def compute_yolo26_segmentation_detection_loss(
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
    """计算 YOLO26 segmentation head 的分类、bbox 和 DFL 损失。"""

    _ = dfl_weight
    foreground_mask = assignment.fg_mask.to(prediction.device).bool()
    foreground_count = int(foreground_mask.sum().item())
    zero_loss = prediction.new_zeros(())

    class_scores = prediction[:, 4 : 4 + int(num_classes)]
    class_targets = torch_module.zeros_like(class_scores, device=prediction.device)
    target_scores = assignment.box_scores.to(
        device=prediction.device, dtype=prediction.dtype
    )
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

    pred_boxes = decode_yolo26_segmentation_training_boxes(
        torch_module=torch_module,
        prediction=prediction,
        anchor_points=anchor_points,
        stride_tensor=stride_tensor,
    )
    target_boxes = assignment.box_targets.to(prediction.device)
    iou = yolo26_box_iou_aligned(
        torch_module=torch_module,
        boxes1=pred_boxes[foreground_mask],
        boxes2=target_boxes[foreground_mask],
    ).clamp(0.0, 1.0)
    foreground_scores = target_scores[foreground_mask]
    box_loss = (
        ((1.0 - iou) * foreground_scores).sum() / target_score_sum
        if int(iou.numel()) > 0
        else zero_loss
    )
    dfl_loss = prediction.new_zeros(())
    if distance_logits is not None and reg_max is not None:
        target_distances = yolo26_bbox_xyxy_to_distances(
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
            raw_dfl_loss = yolo26_distribution_focal_loss(
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
            dfl_loss = (
                raw_dfl_loss.mean(dim=1) * foreground_scores
            ).sum() / target_score_sum
    return class_loss, box_loss, dfl_loss


def decode_yolo26_segmentation_training_boxes(
    *,
    torch_module: Any,
    prediction: Any,
    anchor_points: Any,
    stride_tensor: Any,
) -> Any:
    """按 YOLO26 segmentation 训练坐标系把 ltrb 距离解码成像素级 xyxy。"""

    distances = prediction[:, :4]
    left_top = distances[:, :2]
    right_bottom = distances[:, 2:4]
    anchors = anchor_points.to(device=prediction.device, dtype=prediction.dtype)
    stride = stride_tensor.to(device=prediction.device, dtype=prediction.dtype)
    boxes = torch_module.cat((anchors - left_top, anchors + right_bottom), dim=-1)
    return boxes * stride.repeat(1, 4)


def compute_yolo26_segmentation_mask_loss(
    *,
    torch_module: Any,
    prediction: Any | None,
    proto: Any | None,
    foreground_mask: Any,
    target_masks: Any | None,
    target_mask_valid: Any | None,
    matched_gt_indices: Any | None,
    num_classes: int,
    target_boxes: Any | None = None,
) -> Any:
    """根据 YOLO26 mask coeff、proto 和 matched GT mask 计算实例 mask loss。"""

    if prediction is None or proto is None or target_masks is None:
        return foreground_mask.new_zeros(())
    if target_mask_valid is None or matched_gt_indices is None:
        return foreground_mask.new_zeros(())
    if int(target_masks.shape[0]) == 0:
        return foreground_mask.new_zeros(())

    foreground_mask = foreground_mask.bool()
    matched_gt_indices = matched_gt_indices.to(
        device=foreground_mask.device,
        dtype=torch_module.long,
    )
    target_mask_valid = target_mask_valid.to(device=foreground_mask.device).bool()
    valid_foreground = (
        foreground_mask & target_mask_valid[matched_gt_indices.clamp_min(0)]
    )
    if int(valid_foreground.sum().item()) == 0:
        return foreground_mask.new_zeros(())

    coefficient_start = 4 + int(num_classes)
    mask_coefficients = prediction[valid_foreground, coefficient_start:]
    if int(mask_coefficients.shape[0]) == 0 or int(mask_coefficients.shape[1]) == 0:
        return foreground_mask.new_zeros(())

    proto_channels = int(proto.shape[0])
    if int(mask_coefficients.shape[1]) != proto_channels:
        return foreground_mask.new_zeros(())

    selected_target_masks = (
        target_masks[matched_gt_indices[valid_foreground]]
        .float()
        .to(
            device=prediction.device,
        )
    )
    target_size = (
        int(selected_target_masks.shape[-2]),
        int(selected_target_masks.shape[-1]),
    )
    if tuple(proto.shape[-2:]) != target_size:
        proto = torch_module.nn.functional.interpolate(
            proto.unsqueeze(0),
            size=target_size,
            mode="bilinear",
            align_corners=False,
        ).squeeze(0)

    pred_masks = torch_module.einsum("in,nhw->ihw", mask_coefficients, proto)
    mask_loss = torch_module.nn.functional.binary_cross_entropy_with_logits(
        pred_masks,
        selected_target_masks,
        reduction="none",
    )
    if target_boxes is None:
        return mask_loss.mean()

    selected_boxes = target_boxes.to(device=prediction.device, dtype=prediction.dtype)[
        valid_foreground
    ]
    cropped_loss = crop_yolo26_segmentation_mask_loss(
        torch_module=torch_module,
        mask_loss=mask_loss,
        boxes_xyxy=selected_boxes,
        mask_size=target_size,
    )
    box_area = (selected_boxes[:, 2] - selected_boxes[:, 0]).clamp_min(1.0) * (
        selected_boxes[:, 3] - selected_boxes[:, 1]
    ).clamp_min(1.0)
    mask_height, mask_width = target_size
    normalized_area = box_area / float(mask_height * mask_width)
    instance_loss = cropped_loss.mean(dim=(1, 2)) / normalized_area.clamp_min(1e-6)
    return instance_loss.sum() / valid_foreground.sum().clamp_min(1)


def crop_yolo26_segmentation_mask_loss(
    *,
    torch_module: Any,
    mask_loss: Any,
    boxes_xyxy: Any,
    mask_size: tuple[int, int],
) -> Any:
    """按 bbox 裁剪 YOLO26 segmentation mask loss。"""

    mask_height, mask_width = mask_size
    rows = torch_module.arange(
        mask_width,
        device=mask_loss.device,
        dtype=boxes_xyxy.dtype,
    )[None, None, :]
    cols = torch_module.arange(
        mask_height,
        device=mask_loss.device,
        dtype=boxes_xyxy.dtype,
    )[None, :, None]
    x1 = boxes_xyxy[:, 0].view(-1, 1, 1).clamp(0, mask_width)
    y1 = boxes_xyxy[:, 1].view(-1, 1, 1).clamp(0, mask_height)
    x2 = boxes_xyxy[:, 2].view(-1, 1, 1).clamp(0, mask_width)
    y2 = boxes_xyxy[:, 3].view(-1, 1, 1).clamp(0, mask_height)
    crop_mask = (rows >= x1) & (rows < x2) & (cols >= y1) & (cols < y2)
    return mask_loss * crop_mask.to(mask_loss.dtype)
