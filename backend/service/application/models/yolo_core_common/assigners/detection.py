"""YOLO 主线 detection target assigner。"""

from __future__ import annotations

from typing import Any


def assign_detection_targets(
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
    """按 task-aligned 规则为当前图片分配正样本 anchor。"""

    num_anchors = int(pred_boxes.shape[0])
    num_gt = int(gt_boxes.shape[0])
    if num_gt <= 0 or num_anchors <= 0:
        return {
            "foreground_mask": torch_module.zeros(
                num_anchors,
                dtype=torch_module.bool,
                device=pred_boxes.device,
            ),
            "assigned_gt_indices": torch_module.full(
                (num_anchors,),
                -1,
                dtype=torch_module.long,
                device=pred_boxes.device,
            ),
            "quality_scores": torch_module.zeros(
                num_anchors,
                dtype=pred_boxes.dtype,
                device=pred_boxes.device,
            ),
        }

    inside_mask = build_anchor_inside_mask(
        torch_module=torch_module,
        anchor_centers_xy=anchor_centers_xy,
        gt_boxes=gt_boxes,
    )
    pair_iou = box_iou_matrix(
        torch_module=torch_module,
        boxes1=gt_boxes,
        boxes2=pred_boxes,
    ).clamp(0.0, 1.0)
    gt_class_probabilities = class_probabilities[:, gt_classes].transpose(0, 1).clamp(0.0, 1.0)
    alignment_metric = (gt_class_probabilities.pow(alpha) * pair_iou.pow(beta)) * inside_mask.to(pair_iou.dtype)
    candidate_mask = torch_module.zeros_like(inside_mask)
    gt_centers = (gt_boxes[:, 0:2] + gt_boxes[:, 2:4]) * 0.5
    center_distances = torch_module.cdist(gt_centers, anchor_centers_xy)
    candidate_count = min(max(1, topk), num_anchors)

    for gt_index in range(num_gt):
        gt_metric = alignment_metric[gt_index]
        valid_indices = torch_module.nonzero(gt_metric > 0, as_tuple=False).squeeze(1)
        if int(valid_indices.numel()) == 0:
            fallback_index = int(torch_module.argmin(center_distances[gt_index]).item())
            candidate_mask[gt_index, fallback_index] = True
            alignment_metric[gt_index, fallback_index] = torch_module.maximum(
                alignment_metric[gt_index, fallback_index],
                alignment_metric.new_tensor(1e-4),
            )
            continue
        topk_count = min(candidate_count, int(valid_indices.numel()))
        topk_values, topk_indices = torch_module.topk(gt_metric, k=topk_count)
        valid_topk = topk_values > 0
        if bool(valid_topk.any()):
            candidate_mask[gt_index, topk_indices[valid_topk]] = True
        else:
            fallback_index = int(valid_indices[0].item())
            candidate_mask[gt_index, fallback_index] = True
            alignment_metric[gt_index, fallback_index] = torch_module.maximum(
                alignment_metric[gt_index, fallback_index],
                alignment_metric.new_tensor(1e-4),
            )

    if topk2 is not None and topk2 != topk:
        candidate_mask = _refine_candidate_mask(
            torch_module=torch_module,
            candidate_mask=candidate_mask,
            alignment_metric=alignment_metric,
            topk2=topk2,
            num_anchors=num_anchors,
            num_gt=num_gt,
        )
        alignment_metric = alignment_metric * candidate_mask.to(alignment_metric.dtype)

    matched_metric = alignment_metric * candidate_mask.to(alignment_metric.dtype)
    quality_scores, assigned_gt_indices = matched_metric.max(dim=0)
    foreground_mask = quality_scores > 0
    if bool(foreground_mask.any()):
        matched_gt_indices = assigned_gt_indices[foreground_mask]
        max_metric_per_gt = matched_metric.max(dim=1).values.clamp_min(1e-6)
        normalized_scores = quality_scores[foreground_mask] / max_metric_per_gt[matched_gt_indices]
        quality_scores = quality_scores.clone()
        quality_scores[foreground_mask] = normalized_scores.clamp(0.0, 1.0)
    assigned_gt_indices = assigned_gt_indices.to(dtype=torch_module.long)
    assigned_gt_indices = assigned_gt_indices.where(
        foreground_mask,
        torch_module.full_like(assigned_gt_indices, -1),
    )
    return {
        "foreground_mask": foreground_mask,
        "assigned_gt_indices": assigned_gt_indices,
        "quality_scores": quality_scores,
    }


def build_anchor_inside_mask(
    *,
    torch_module: Any,
    anchor_centers_xy: Any,
    gt_boxes: Any,
) -> Any:
    """判断 anchor center 是否落在 gt bbox 内部。"""

    center_x = anchor_centers_xy[:, 0].unsqueeze(0)
    center_y = anchor_centers_xy[:, 1].unsqueeze(0)
    return (
        (center_x >= gt_boxes[:, 0:1])
        & (center_x <= gt_boxes[:, 2:3])
        & (center_y >= gt_boxes[:, 1:2])
        & (center_y <= gt_boxes[:, 3:4])
    )


def box_iou_matrix(
    *,
    torch_module: Any,
    boxes1: Any,
    boxes2: Any,
) -> Any:
    """计算两组 xyxy bbox 的两两 IoU。"""

    if int(boxes1.shape[0]) == 0 or int(boxes2.shape[0]) == 0:
        return torch_module.zeros(
            (int(boxes1.shape[0]), int(boxes2.shape[0])),
            device=boxes1.device,
            dtype=boxes1.dtype,
        )
    top_left = torch_module.maximum(boxes1[:, None, 0:2], boxes2[None, :, 0:2])
    bottom_right = torch_module.minimum(boxes1[:, None, 2:4], boxes2[None, :, 2:4])
    overlap = (bottom_right - top_left).clamp_min(0.0)
    intersection = overlap[..., 0] * overlap[..., 1]
    area1 = (
        (boxes1[:, 2] - boxes1[:, 0]).clamp_min(0.0)
        * (boxes1[:, 3] - boxes1[:, 1]).clamp_min(0.0)
    ).unsqueeze(1)
    area2 = (
        (boxes2[:, 2] - boxes2[:, 0]).clamp_min(0.0)
        * (boxes2[:, 3] - boxes2[:, 1]).clamp_min(0.0)
    ).unsqueeze(0)
    union = area1 + area2 - intersection
    return intersection / union.clamp_min(1e-6)


def box_iou_aligned(
    *,
    torch_module: Any,
    boxes1: Any,
    boxes2: Any,
) -> Any:
    """计算一一对应的两组 bbox IoU。"""

    top_left = torch_module.maximum(boxes1[:, 0:2], boxes2[:, 0:2])
    bottom_right = torch_module.minimum(boxes1[:, 2:4], boxes2[:, 2:4])
    overlap = (bottom_right - top_left).clamp_min(0.0)
    intersection = overlap[:, 0] * overlap[:, 1]
    area1 = (boxes1[:, 2] - boxes1[:, 0]).clamp_min(0.0) * (boxes1[:, 3] - boxes1[:, 1]).clamp_min(0.0)
    area2 = (boxes2[:, 2] - boxes2[:, 0]).clamp_min(0.0) * (boxes2[:, 3] - boxes2[:, 1]).clamp_min(0.0)
    union = area1 + area2 - intersection
    return intersection / union.clamp_min(1e-6)


def _refine_candidate_mask(
    *,
    torch_module: Any,
    candidate_mask: Any,
    alignment_metric: Any,
    topk2: int,
    num_anchors: int,
    num_gt: int,
) -> Any:
    """对初始 topk 候选执行二次精选。"""

    refined_metric = alignment_metric * candidate_mask.to(alignment_metric.dtype)
    refined_topk = min(max(1, topk2), num_anchors)
    refined_candidate_mask = torch_module.zeros_like(candidate_mask)
    for gt_index in range(num_gt):
        gt_refined_metric = refined_metric[gt_index]
        valid_indices = torch_module.nonzero(gt_refined_metric > 0, as_tuple=False).squeeze(1)
        if int(valid_indices.numel()) == 0:
            refined_candidate_mask[gt_index] = candidate_mask[gt_index]
            continue
        refined_count = min(refined_topk, int(valid_indices.numel()))
        refined_values, refined_indices = torch_module.topk(gt_refined_metric, k=refined_count)
        valid_refined = refined_values > 0
        if bool(valid_refined.any()):
            refined_candidate_mask[gt_index, refined_indices[valid_refined]] = True
        else:
            refined_candidate_mask[gt_index] = candidate_mask[gt_index]
    return refined_candidate_mask
