"""YOLO segmentation 共用 mask loss。"""

from __future__ import annotations

from typing import Any


def compute_segmentation_detection_loss(
    *,
    torch_module: Any,
    prediction: Any,
    assignment: Any,
    anchor_points: Any,
    stride_tensor: Any,
    dfl_weight: float,
    num_classes: int,
) -> tuple[Any, Any, Any]:
    """计算 segmentation head 共用的分类、bbox 和 DFL 占位损失。"""

    _ = stride_tensor, dfl_weight
    foreground_mask = assignment.fg_mask.to(prediction.device).bool()
    foreground_count = int(foreground_mask.sum().item())
    zero_loss = prediction.new_zeros(())
    if foreground_count <= 0:
        return zero_loss, zero_loss, zero_loss

    class_scores = prediction[:, 4 : 4 + int(num_classes)]
    class_targets = torch_module.zeros_like(class_scores, device=prediction.device)
    class_targets[
        torch_module.arange(class_targets.shape[0], device=prediction.device),
        assignment.class_ids.to(prediction.device),
    ] = 1.0
    class_loss_full = torch_module.nn.BCEWithLogitsLoss(reduction="none")(
        class_scores,
        class_targets,
    ).mean(dim=-1)
    class_loss = (class_loss_full * foreground_mask.float()).sum() / max(1, foreground_count)

    pred_boxes = decode_segmentation_training_boxes(
        torch_module=torch_module,
        prediction=prediction,
        anchor_points=anchor_points,
    )
    target_boxes = assignment.box_targets.to(prediction.device)
    iou = segmentation_bbox_iou_aligned(
        torch_module=torch_module,
        boxes1=pred_boxes[foreground_mask],
        boxes2=target_boxes[foreground_mask],
    )
    box_loss = (1.0 - iou).mean() if int(iou.numel()) > 0 else zero_loss
    dfl_loss = prediction.new_zeros(())
    return class_loss, box_loss, dfl_loss


def decode_segmentation_training_boxes(
    *,
    torch_module: Any,
    prediction: Any,
    anchor_points: Any,
) -> Any:
    """按当前 segmentation 训练坐标系把 ltrb 距离解码成 xyxy。"""

    distances = prediction[:, :4]
    left_top = distances[:, :2]
    right_bottom = distances[:, 2:4]
    anchors = anchor_points.to(device=prediction.device, dtype=prediction.dtype)
    return torch_module.cat((anchors - left_top, anchors + right_bottom), dim=-1)


def segmentation_bbox_iou_aligned(
    *,
    torch_module: Any,
    boxes1: Any,
    boxes2: Any,
    eps: float = 1e-7,
) -> Any:
    """计算一一对应的 segmentation bbox IoU。"""

    if int(boxes1.shape[0]) == 0 or int(boxes2.shape[0]) == 0:
        return torch_module.zeros(
            (0,),
            device=boxes1.device,
            dtype=boxes1.dtype,
        )
    intersection_width = (
        torch_module.minimum(boxes1[:, 2], boxes2[:, 2])
        - torch_module.maximum(boxes1[:, 0], boxes2[:, 0])
    ).clamp(0)
    intersection_height = (
        torch_module.minimum(boxes1[:, 3], boxes2[:, 3])
        - torch_module.maximum(boxes1[:, 1], boxes2[:, 1])
    ).clamp(0)
    intersection = intersection_width * intersection_height
    area1 = (boxes1[:, 2] - boxes1[:, 0]) * (boxes1[:, 3] - boxes1[:, 1])
    area2 = (boxes2[:, 2] - boxes2[:, 0]) * (boxes2[:, 3] - boxes2[:, 1])
    return intersection / (area1 + area2 - intersection + eps)


def compute_segmentation_mask_loss(
    *,
    torch_module: Any,
    prediction: Any | None,
    proto: Any | None,
    foreground_mask: Any,
    target_masks: Any | None,
    target_mask_valid: Any | None,
    matched_gt_indices: Any | None,
    num_classes: int,
) -> Any:
    """根据 mask coeff、proto 和 matched GT mask 计算实例 mask BCE loss。

    参数：
    - torch_module：PyTorch 模块。
    - prediction：单张图预测，shape 为 ``(N, 4 + num_classes + nm)``。
    - proto：单张图 proto mask，shape 为 ``(nm, H, W)``。
    - foreground_mask：正样本 anchor mask，shape 为 ``(N,)``。
    - target_masks：GT mask，shape 为 ``(M, H0, W0)``。
    - target_mask_valid：GT mask 是否有效，shape 为 ``(M,)``。
    - matched_gt_indices：每个 anchor 匹配的 GT index，shape 为 ``(N,)``。
    - num_classes：类别数。

    返回：
    - 标量 mask loss。缺少 mask target 或没有有效正样本时返回 0。
    """

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
    valid_foreground = foreground_mask & target_mask_valid[matched_gt_indices.clamp_min(0)]
    if int(valid_foreground.sum().item()) == 0:
        return foreground_mask.new_zeros(())

    coefficient_start = 4 + int(num_classes)
    mask_coefficients = prediction[valid_foreground, coefficient_start:]
    if int(mask_coefficients.shape[0]) == 0 or int(mask_coefficients.shape[1]) == 0:
        return foreground_mask.new_zeros(())

    proto_channels = int(proto.shape[0])
    if int(mask_coefficients.shape[1]) != proto_channels:
        return foreground_mask.new_zeros(())

    proto_flat = proto.reshape(proto_channels, -1)
    pred_masks = torch_module.sigmoid(mask_coefficients @ proto_flat)
    selected_target_masks = target_masks[matched_gt_indices[valid_foreground]].float().to(
        device=prediction.device,
    )
    proto_size = (int(proto.shape[-2]), int(proto.shape[-1]))
    if selected_target_masks.shape[-2:] != proto_size:
        selected_target_masks = torch_module.nn.functional.interpolate(
            selected_target_masks.unsqueeze(1),
            size=proto_size,
            mode="nearest",
        ).squeeze(1)
    target_flat = selected_target_masks.reshape(int(selected_target_masks.shape[0]), -1)
    return torch_module.nn.functional.binary_cross_entropy(
        pred_masks,
        target_flat,
        reduction="mean",
    )
