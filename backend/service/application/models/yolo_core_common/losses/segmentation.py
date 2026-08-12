"""三代 YOLO 共用的实例分割 mask loss。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class YoloSegmentationDetectionLossTerms:
    """保存一张图片尚未按 batch 归一化的 detection loss 分子。"""

    class_loss_sum: Any
    box_loss_sum: Any
    dfl_loss_sum: Any
    target_score_sum: Any


@dataclass(frozen=True)
class YoloSegmentationMaskLossTerms:
    """保存一张图片尚未按 batch 归一化的 mask loss 分子。"""

    mask_loss_sum: Any
    foreground_count: int


def finalize_yolo_segmentation_detection_loss_terms(
    *,
    torch_module: Any,
    terms: list[YoloSegmentationDetectionLossTerms],
    batch_size: int,
) -> tuple[Any, Any, Any]:
    """按 Ultralytics 全 batch target score 口径完成 detection loss。"""

    if not terms:
        raise ValueError("segmentation detection loss terms 不能为空")
    class_loss_sum = torch_module.stack(
        [item.class_loss_sum.reshape(()) for item in terms]
    ).sum()
    box_loss_sum = torch_module.stack(
        [item.box_loss_sum.reshape(()) for item in terms]
    ).sum()
    dfl_loss_sum = torch_module.stack(
        [item.dfl_loss_sum.reshape(()) for item in terms]
    ).sum()
    target_score_sum = torch_module.stack(
        [item.target_score_sum.reshape(()) for item in terms]
    ).sum()
    normalizer = target_score_sum.clamp_min(1.0)
    scale = max(1, int(batch_size))
    return (
        class_loss_sum / normalizer * scale,
        box_loss_sum / normalizer * scale,
        dfl_loss_sum / normalizer * scale,
    )


def finalize_yolo_segmentation_mask_loss_terms(
    *,
    torch_module: Any,
    terms: list[YoloSegmentationMaskLossTerms],
    batch_size: int,
) -> Any:
    """按 Ultralytics 全 batch foreground 口径完成实例 mask loss。"""

    if not terms:
        raise ValueError("segmentation mask loss terms 不能为空")
    mask_loss_sum = torch_module.stack(
        [item.mask_loss_sum.reshape(()) for item in terms]
    ).sum()
    foreground_count = sum(max(0, int(item.foreground_count)) for item in terms)
    return mask_loss_sum / max(1, foreground_count) * max(1, int(batch_size))


def compute_yolo_segmentation_mask_loss_terms(
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
    image_size: tuple[int, int] | None = None,
) -> YoloSegmentationMaskLossTerms:
    """按 Ultralytics 坐标规则计算单张图片未归一化的 mask loss。

    ``target_boxes`` 使用输入图片像素坐标，``target_masks`` 通常按
    ``mask_ratio=4`` 下采样。裁剪前必须先把 bbox 映射到 mask 空间，面积
    则按输入图归一化；二者不能混用同一组原始像素值。
    """

    zero_loss = _zero_segmentation_mask_loss(
        foreground_mask=foreground_mask,
        prediction=prediction,
        proto=proto,
    )
    if prediction is None or proto is None or target_masks is None:
        return YoloSegmentationMaskLossTerms(zero_loss, 0)
    if target_mask_valid is None or matched_gt_indices is None:
        return YoloSegmentationMaskLossTerms(zero_loss, 0)
    if int(target_masks.shape[0]) == 0:
        return YoloSegmentationMaskLossTerms(zero_loss, 0)

    foreground_mask = foreground_mask.bool()
    matched_gt_indices = matched_gt_indices.to(
        device=foreground_mask.device,
        dtype=torch_module.long,
    )
    target_mask_valid = target_mask_valid.to(device=foreground_mask.device).bool()
    valid_foreground = (
        foreground_mask & target_mask_valid[matched_gt_indices.clamp_min(0)]
    )
    valid_count = int(valid_foreground.sum().item())
    if valid_count == 0:
        return YoloSegmentationMaskLossTerms(zero_loss, 0)

    coefficient_start = 4 + int(num_classes)
    mask_coefficients = prediction[valid_foreground, coefficient_start:]
    proto_channels = int(proto.shape[0])
    if int(mask_coefficients.shape[1]) != proto_channels:
        raise ValueError(
            "segmentation mask coefficient 数量与 proto channel 不一致: "
            f"coefficients={int(mask_coefficients.shape[1])}, "
            f"proto_channels={proto_channels}"
        )

    selected_target_masks = (
        target_masks[matched_gt_indices[valid_foreground]]
        .float()
        .to(device=prediction.device)
    )
    mask_height = int(selected_target_masks.shape[-2])
    mask_width = int(selected_target_masks.shape[-1])
    if tuple(proto.shape[-2:]) != (mask_height, mask_width):
        proto = torch_module.nn.functional.interpolate(
            proto.unsqueeze(0),
            size=(mask_height, mask_width),
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
        return YoloSegmentationMaskLossTerms(
            mask_loss.mean(dim=(1, 2)).sum(),
            valid_count,
        )

    selected_boxes = target_boxes.to(
        device=prediction.device,
        dtype=prediction.dtype,
    )[valid_foreground]
    input_height, input_width = _resolve_segmentation_image_size(
        image_size=image_size,
        mask_size=(mask_height, mask_width),
    )
    scale = selected_boxes.new_tensor(
        (
            mask_width / float(input_width),
            mask_height / float(input_height),
            mask_width / float(input_width),
            mask_height / float(input_height),
        )
    )
    boxes_in_mask_space = selected_boxes * scale
    cropped_loss = crop_yolo_segmentation_mask_loss(
        torch_module=torch_module,
        mask_loss=mask_loss,
        boxes_xyxy=boxes_in_mask_space,
        mask_size=(mask_height, mask_width),
    )
    normalized_width = (
        (selected_boxes[:, 2] - selected_boxes[:, 0]).clamp_min(1.0)
        / float(input_width)
    )
    normalized_height = (
        (selected_boxes[:, 3] - selected_boxes[:, 1]).clamp_min(1.0)
        / float(input_height)
    )
    normalized_area = (normalized_width * normalized_height).clamp_min(1e-6)
    instance_loss = cropped_loss.mean(dim=(1, 2)) / normalized_area
    return YoloSegmentationMaskLossTerms(instance_loss.sum(), valid_count)


def compute_yolo_segmentation_mask_loss(
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
    image_size: tuple[int, int] | None = None,
) -> Any:
    """兼容单图入口，按该图 foreground 数量返回平均 mask loss。"""

    terms = compute_yolo_segmentation_mask_loss_terms(
        torch_module=torch_module,
        prediction=prediction,
        proto=proto,
        foreground_mask=foreground_mask,
        target_masks=target_masks,
        target_mask_valid=target_mask_valid,
        matched_gt_indices=matched_gt_indices,
        num_classes=num_classes,
        target_boxes=target_boxes,
        image_size=image_size,
    )
    return terms.mask_loss_sum / max(1, terms.foreground_count)


def _zero_segmentation_mask_loss(
    *,
    foreground_mask: Any,
    prediction: Any | None,
    proto: Any | None,
) -> Any:
    """构建保留 mask head 计算图的零 loss。"""

    zero_loss = foreground_mask.new_zeros(())
    if prediction is not None:
        zero_loss = zero_loss + prediction.sum() * 0.0
    if proto is not None:
        zero_loss = zero_loss + proto.sum() * 0.0
    return zero_loss


def crop_yolo_segmentation_mask_loss(
    *,
    torch_module: Any,
    mask_loss: Any,
    boxes_xyxy: Any,
    mask_size: tuple[int, int],
) -> Any:
    """按 mask 空间的 bbox 裁剪逐像素 loss。"""

    mask_height, mask_width = (int(mask_size[0]), int(mask_size[1]))
    columns = torch_module.arange(
        mask_width,
        device=mask_loss.device,
        dtype=boxes_xyxy.dtype,
    )[None, None, :]
    rows = torch_module.arange(
        mask_height,
        device=mask_loss.device,
        dtype=boxes_xyxy.dtype,
    )[None, :, None]
    x1 = boxes_xyxy[:, 0].view(-1, 1, 1).clamp(0, mask_width)
    y1 = boxes_xyxy[:, 1].view(-1, 1, 1).clamp(0, mask_height)
    x2 = boxes_xyxy[:, 2].view(-1, 1, 1).clamp(0, mask_width)
    y2 = boxes_xyxy[:, 3].view(-1, 1, 1).clamp(0, mask_height)
    crop_mask = (
        (columns >= x1)
        & (columns < x2)
        & (rows >= y1)
        & (rows < y2)
    )
    return mask_loss * crop_mask.to(mask_loss.dtype)


def compute_yolo26_semantic_segmentation_loss(
    *,
    torch_module: Any,
    pred_semantic: Any | None,
    targets_list: list[dict[str, Any]],
    num_classes: int,
) -> Any:
    """计算 YOLO26 Segment26 的 BCE + multi-channel Dice 辅助损失。

    Segment26 的 ``Proto26`` 除实例 proto 外还包含 semantic branch。目标由
    当前 batch 的实例 mask 和 class id 构建；重叠像素按参考数据管线规则
    选择面积最小的实例，背景像素在所有类别通道保持为零。
    """

    if pred_semantic is None:
        if targets_list:
            masks = targets_list[0].get("masks")
            if masks is not None:
                return masks.new_zeros(())
        raise ValueError("pred_semantic 和可用于构造零 loss 的 target 不能同时为空")
    batch_size = int(pred_semantic.shape[0])
    if batch_size != len(targets_list):
        raise ValueError(
            "semantic prediction batch 与 target 数量不一致: "
            f"predictions={batch_size}, targets={len(targets_list)}"
        )
    target_batches: list[Any] = []
    has_valid_instance = False
    for target in targets_list:
        masks = target.get("masks")
        class_ids = target.get("class_ids")
        mask_valid = target.get("mask_valid")
        semantic_target, image_has_instance = _build_yolo_semantic_target(
            torch_module=torch_module,
            masks=masks,
            class_ids=class_ids,
            mask_valid=mask_valid,
            num_classes=num_classes,
            device=pred_semantic.device,
            dtype=pred_semantic.dtype,
        )
        target_size = tuple(int(value) for value in pred_semantic.shape[-2:])
        if tuple(int(value) for value in semantic_target.shape[-2:]) != target_size:
            # 空图没有实例 mask 可提供 H/W，可能得到 1x1 target；非空图通常
            # 仍处于输入图分辨率。必须逐图统一到 semantic head 分辨率后再
            # stack，既避免混合 batch shape 崩溃，也避免先堆叠高分辨率张量。
            semantic_target = torch_module.nn.functional.interpolate(
                semantic_target.unsqueeze(0),
                size=target_size,
                mode="nearest",
            ).squeeze(0)
        target_batches.append(semantic_target)
        has_valid_instance = has_valid_instance or image_has_instance
    if not has_valid_instance:
        return pred_semantic.sum() * 0.0

    semantic_targets = torch_module.stack(target_batches, dim=0)
    bce_loss = torch_module.nn.functional.binary_cross_entropy_with_logits(
        pred_semantic,
        semantic_targets,
    )
    probabilities = pred_semantic.sigmoid()
    intersection = (probabilities * semantic_targets).sum(dim=(2, 3))
    union = probabilities.sum(dim=(2, 3)) + semantic_targets.sum(dim=(2, 3))
    dice_loss = (1.0 - (2.0 * intersection + 1.0) / (union + 1.0)).mean()
    return 0.5 * bce_loss + 0.5 * dice_loss


def _build_yolo_semantic_target(
    *,
    torch_module: Any,
    masks: Any | None,
    class_ids: Any | None,
    mask_valid: Any | None,
    num_classes: int,
    device: Any,
    dtype: Any,
) -> tuple[Any, bool]:
    """由单图实例 mask 构建 YOLO26 semantic one-hot target。"""

    if masks is None or int(masks.shape[0]) == 0:
        # 空图仍需稳定的空间尺寸；训练 batch 的 mask tensor 保留 H/W。
        height = int(masks.shape[-2]) if masks is not None else 1
        width = int(masks.shape[-1]) if masks is not None else 1
        return torch_module.zeros(
            (int(num_classes), height, width),
            device=device,
            dtype=dtype,
        ), False
    resolved_masks = masks.to(device=device).bool()
    resolved_classes = torch_module.as_tensor(
        class_ids,
        device=device,
        dtype=torch_module.long,
    ).view(-1)
    if int(resolved_classes.shape[0]) != int(resolved_masks.shape[0]):
        raise ValueError("semantic target 的 class id 数量与实例 mask 数量不一致")
    if mask_valid is not None:
        valid = torch_module.as_tensor(
            mask_valid,
            device=device,
            dtype=torch_module.bool,
        ).view(-1)
        if int(valid.shape[0]) != int(resolved_masks.shape[0]):
            raise ValueError("semantic target 的 mask_valid 数量与实例 mask 数量不一致")
        resolved_masks = resolved_masks[valid]
        resolved_classes = resolved_classes[valid]
    if int(resolved_masks.shape[0]) == 0:
        return torch_module.zeros(
            (int(num_classes), int(masks.shape[-2]), int(masks.shape[-1])),
            device=device,
            dtype=dtype,
        ), False
    if bool(((resolved_classes < 0) | (resolved_classes >= int(num_classes))).any()):
        raise ValueError("semantic target 包含越界 class id")

    present = resolved_masks.any(dim=0)
    areas = resolved_masks.flatten(1).sum(dim=1).to(dtype=dtype)
    candidate_areas = areas[:, None, None].expand_as(resolved_masks).clone()
    candidate_areas = candidate_areas.masked_fill(
        ~resolved_masks,
        torch_module.finfo(dtype).max,
    )
    selected_instance = candidate_areas.argmin(dim=0)
    semantic_index = resolved_classes[selected_instance]
    semantic_target = torch_module.zeros(
        (int(num_classes), int(resolved_masks.shape[-2]), int(resolved_masks.shape[-1])),
        device=device,
        dtype=dtype,
    )
    semantic_target.scatter_(
        0,
        semantic_index.unsqueeze(0),
        present.unsqueeze(0).to(dtype=dtype),
    )
    return semantic_target, True


def _resolve_segmentation_image_size(
    *,
    image_size: tuple[int, int] | None,
    mask_size: tuple[int, int],
) -> tuple[int, int]:
    """校验并返回 bbox 所在的输入图尺寸。"""

    resolved = image_size or mask_size
    height, width = (int(resolved[0]), int(resolved[1]))
    if height < 1 or width < 1:
        raise ValueError("segmentation image_size 必须为正整数")
    return height, width


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
    """计算旧共用 segmentation head 的分类、bbox 和 DFL 占位损失。"""

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
    class_loss = (class_loss_full * foreground_mask.float()).sum() / max(
        1,
        foreground_count,
    )

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
    return class_loss, box_loss, zero_loss


def decode_segmentation_training_boxes(
    *,
    torch_module: Any,
    prediction: Any,
    anchor_points: Any,
) -> Any:
    """按旧共用 segmentation 坐标系把 ltrb 距离解码成 xyxy。"""

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
    """执行不带 bbox crop 的通用 segmentation mask loss。"""

    return compute_yolo_segmentation_mask_loss(
        torch_module=torch_module,
        prediction=prediction,
        proto=proto,
        foreground_mask=foreground_mask,
        target_masks=target_masks,
        target_mask_valid=target_mask_valid,
        matched_gt_indices=matched_gt_indices,
        num_classes=num_classes,
    )


__all__ = [
    "YoloSegmentationDetectionLossTerms",
    "YoloSegmentationMaskLossTerms",
    "compute_segmentation_detection_loss",
    "compute_segmentation_mask_loss",
    "compute_yolo26_semantic_segmentation_loss",
    "compute_yolo_segmentation_mask_loss",
    "compute_yolo_segmentation_mask_loss_terms",
    "crop_yolo_segmentation_mask_loss",
    "decode_segmentation_training_boxes",
    "finalize_yolo_segmentation_detection_loss_terms",
    "finalize_yolo_segmentation_mask_loss_terms",
    "segmentation_bbox_iou_aligned",
]
