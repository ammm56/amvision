"""YOLO26 detection target assigner。"""

from __future__ import annotations

import math
from typing import Any


def assign_yolo26_detection_targets(
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
    """按 YOLO26 detection task-aligned 规则分配正样本 anchor。"""

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

    inside_mask = _build_yolo26_anchor_inside_mask(
        torch_module=torch_module,
        anchor_centers_xy=anchor_centers_xy,
        gt_boxes=gt_boxes,
    )
    pair_iou = yolo26_box_iou_matrix(
        torch_module=torch_module,
        boxes1=gt_boxes,
        boxes2=pred_boxes,
    ).clamp(0.0, 1.0)
    gt_class_probabilities = (
        class_probabilities[:, gt_classes].transpose(0, 1).clamp(0.0, 1.0)
    )
    alignment_metric = (
        gt_class_probabilities.pow(alpha)
        * pair_iou.pow(beta)
        * inside_mask.to(pair_iou.dtype)
    )
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
        candidate_mask = _refine_yolo26_candidate_mask(
            torch_module=torch_module,
            candidate_mask=candidate_mask,
            alignment_metric=alignment_metric,
            topk2=topk2,
            num_anchors=num_anchors,
            num_gt=num_gt,
        )
        alignment_metric = alignment_metric * candidate_mask.to(alignment_metric.dtype)

    candidate_weight = candidate_mask.to(alignment_metric.dtype)
    matched_metric = alignment_metric * candidate_weight
    matched_iou = pair_iou * candidate_weight
    quality_scores, assigned_gt_indices = matched_metric.max(dim=0)
    foreground_mask = quality_scores > 0
    if bool(foreground_mask.any()):
        matched_gt_indices = assigned_gt_indices[foreground_mask]
        max_metric_per_gt = matched_metric.max(dim=1).values.clamp_min(1e-6)
        max_iou_per_gt = matched_iou.max(dim=1).values.clamp(0.0, 1.0)
        normalized_scores = (
            quality_scores[foreground_mask]
            * max_iou_per_gt[matched_gt_indices]
            / max_metric_per_gt[matched_gt_indices]
        )
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


def yolo26_box_iou_matrix(
    *,
    torch_module: Any,
    boxes1: Any,
    boxes2: Any,
) -> Any:
    """计算两组 xyxy bbox 的两两 CIoU。"""

    if int(boxes1.shape[0]) == 0 or int(boxes2.shape[0]) == 0:
        return torch_module.zeros(
            (int(boxes1.shape[0]), int(boxes2.shape[0])),
            device=boxes1.device,
            dtype=boxes1.dtype,
        )
    return _yolo26_box_ciou_matrix(
        torch_module=torch_module, boxes1=boxes1, boxes2=boxes2
    )


def yolo26_box_iou_aligned(
    *,
    torch_module: Any,
    boxes1: Any,
    boxes2: Any,
) -> Any:
    """计算一一对应的两组 bbox CIoU。"""

    if int(boxes1.shape[0]) == 0:
        return torch_module.zeros(
            (0,),
            device=boxes1.device,
            dtype=boxes1.dtype,
        )
    ciou = _yolo26_box_ciou_matrix(
        torch_module=torch_module,
        boxes1=boxes1,
        boxes2=boxes2,
    )
    return ciou.diagonal()


def _yolo26_box_ciou_matrix(
    *,
    torch_module: Any,
    boxes1: Any,
    boxes2: Any,
) -> Any:
    """按 xyxy bbox 计算 CIoU 矩阵。"""

    top_left = torch_module.maximum(boxes1[:, None, 0:2], boxes2[None, :, 0:2])
    bottom_right = torch_module.minimum(boxes1[:, None, 2:4], boxes2[None, :, 2:4])
    overlap = (bottom_right - top_left).clamp_min(0.0)
    intersection = overlap[..., 0] * overlap[..., 1]

    box1_size = (boxes1[:, 2:4] - boxes1[:, 0:2]).clamp_min(0.0)
    box2_size = (boxes2[:, 2:4] - boxes2[:, 0:2]).clamp_min(0.0)
    area1 = (box1_size[:, 0] * box1_size[:, 1]).unsqueeze(1)
    area2 = (box2_size[:, 0] * box2_size[:, 1]).unsqueeze(0)
    union = (area1 + area2 - intersection).clamp_min(1e-6)
    iou = intersection / union

    box1_center = (boxes1[:, 0:2] + boxes1[:, 2:4]) * 0.5
    box2_center = (boxes2[:, 0:2] + boxes2[:, 2:4]) * 0.5
    center_distance = ((box1_center[:, None, :] - box2_center[None, :, :]) ** 2).sum(
        dim=-1
    )

    enclosing_top_left = torch_module.minimum(
        boxes1[:, None, 0:2], boxes2[None, :, 0:2]
    )
    enclosing_bottom_right = torch_module.maximum(
        boxes1[:, None, 2:4], boxes2[None, :, 2:4]
    )
    enclosing_size = (enclosing_bottom_right - enclosing_top_left).clamp_min(0.0)
    enclosing_distance = (enclosing_size**2).sum(dim=-1).clamp_min(1e-6)

    box1_width = box1_size[:, 0].clamp_min(1e-6).unsqueeze(1)
    box1_height = box1_size[:, 1].clamp_min(1e-6).unsqueeze(1)
    box2_width = box2_size[:, 0].clamp_min(1e-6).unsqueeze(0)
    box2_height = box2_size[:, 1].clamp_min(1e-6).unsqueeze(0)
    aspect_delta = torch_module.atan(box2_width / box2_height) - torch_module.atan(
        box1_width / box1_height
    )
    aspect_penalty = (4.0 / math.pi**2) * aspect_delta.pow(2)
    with torch_module.no_grad():
        aspect_weight = aspect_penalty / (aspect_penalty - iou + 1.0 + 1e-6)
    return iou - (center_distance / enclosing_distance + aspect_weight * aspect_penalty)


def _build_yolo26_anchor_inside_mask(
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


def _refine_yolo26_candidate_mask(
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
    refined_mask = torch_module.zeros_like(candidate_mask)
    refine_count = min(max(1, topk2), num_anchors)
    for gt_index in range(num_gt):
        valid_indices = torch_module.nonzero(
            refined_metric[gt_index] > 0, as_tuple=False
        ).squeeze(1)
        if int(valid_indices.numel()) == 0:
            continue
        topk_count = min(refine_count, int(valid_indices.numel()))
        _, topk_indices = torch_module.topk(refined_metric[gt_index], k=topk_count)
        refined_mask[gt_index, topk_indices] = True
    return refined_mask
