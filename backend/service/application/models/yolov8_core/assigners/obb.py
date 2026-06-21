"""YOLOv8 OBB target assigner。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolov8_core.targets import (
    yolov8_anchor_in_rotated_box,
    yolov8_xywhr_to_corners,
)


def assign_yolov8_obb_targets(
    *,
    torch_module: Any,
    pred_rboxes: Any,
    class_probabilities: Any,
    anchor_centers_xy: Any,
    gt_rboxes: Any,
    gt_classes: Any,
    topk: int,
    alpha: float,
    beta: float,
    min_candidate_box_size: float = 0.0,
) -> dict[str, Any]:
    """按 YOLOv8 OBB 的旋转框 TAL 规则分配正样本。"""

    num_gt = int(gt_rboxes.shape[0])
    num_anchors = int(pred_rboxes.shape[0])
    if num_gt <= 0 or num_anchors <= 0:
        return {
            "foreground_mask": torch_module.zeros(
                num_anchors,
                dtype=torch_module.bool,
                device=pred_rboxes.device,
            ),
            "assigned_gt_indices": torch_module.full(
                (num_anchors,),
                -1,
                dtype=torch_module.long,
                device=pred_rboxes.device,
            ),
            "quality_scores": torch_module.zeros(
                num_anchors,
                dtype=pred_rboxes.dtype,
                device=pred_rboxes.device,
            ),
        }

    from backend.service.application.models.yolov8_core.losses.obb import yolov8_probiou_aligned

    gt_expanded = gt_rboxes.unsqueeze(1).expand(-1, num_anchors, -1).reshape(-1, 5)
    pred_expanded = pred_rboxes.detach().unsqueeze(0).expand(num_gt, -1, -1).reshape(-1, 5)
    pair_iou = yolov8_probiou_aligned(
        torch_module=torch_module,
        obb1=gt_expanded,
        obb2=pred_expanded,
    ).view(num_gt, num_anchors).clamp(0.0, 1.0)
    gt_class_probs = class_probabilities.detach()[:, gt_classes].t().clamp(0.0, 1.0)
    alignment_metric = gt_class_probs.pow(alpha) * pair_iou.pow(beta)

    candidate_gt_rboxes = _build_yolov8_obb_candidate_boxes(
        torch_module=torch_module,
        gt_rboxes=gt_rboxes,
        min_candidate_box_size=min_candidate_box_size,
    )
    gt_corners = yolov8_xywhr_to_corners(
        torch_module=torch_module,
        rboxes=candidate_gt_rboxes,
    )
    inside_mask = yolov8_anchor_in_rotated_box(
        torch_module=torch_module,
        anchor_points=anchor_centers_xy,
        corners=gt_corners,
    )
    alignment_metric = alignment_metric * inside_mask.to(alignment_metric.dtype)

    candidate_mask = _select_yolov8_obb_candidates(
        torch_module=torch_module,
        alignment_metric=alignment_metric,
        inside_mask=inside_mask,
        gt_rboxes=candidate_gt_rboxes,
        anchor_centers_xy=anchor_centers_xy,
        topk=topk,
        num_gt=num_gt,
        num_anchors=num_anchors,
    )
    candidate_weight = candidate_mask.to(alignment_metric.dtype)
    matched_metric = alignment_metric * candidate_weight
    matched_iou = pair_iou * candidate_weight
    selection_metric = torch_module.where(
        candidate_mask,
        matched_metric,
        matched_metric.new_full(matched_metric.shape, -1.0),
    )
    _, assigned_gt_indices = selection_metric.max(dim=0)
    foreground_mask = candidate_mask.any(dim=0)
    quality_scores = matched_metric.gather(0, assigned_gt_indices.unsqueeze(0)).squeeze(0)
    quality_scores = quality_scores.where(
        foreground_mask,
        torch_module.zeros_like(quality_scores),
    )
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
        "matched_metric": matched_metric,
    }


def _select_yolov8_obb_candidates(
    *,
    torch_module: Any,
    alignment_metric: Any,
    inside_mask: Any,
    gt_rboxes: Any,
    anchor_centers_xy: Any,
    topk: int,
    num_gt: int,
    num_anchors: int,
) -> Any:
    """选择 YOLOv8 OBB TAL 候选 anchor。"""

    candidate_mask = torch_module.zeros(
        (num_gt, num_anchors),
        dtype=torch_module.bool,
        device=alignment_metric.device,
    )
    topk_count = min(max(1, int(topk)), num_anchors)
    for gt_index in range(num_gt):
        selected_count = min(topk_count, int(alignment_metric[gt_index].numel()))
        _, topk_indices = torch_module.topk(
            alignment_metric[gt_index],
            k=selected_count,
        )
        candidate_mask[gt_index, topk_indices] = True
    return candidate_mask & inside_mask


def _build_yolov8_obb_candidate_boxes(
    *,
    torch_module: Any,
    gt_rboxes: Any,
    min_candidate_box_size: float,
) -> Any:
    """构造 OBB TAL 候选筛选使用的旋转框。"""

    if min_candidate_box_size <= 0:
        return gt_rboxes
    min_size = gt_rboxes.new_tensor(float(min_candidate_box_size))
    candidate_boxes = gt_rboxes.clone()
    candidate_boxes[:, 2:4] = torch_module.where(
        candidate_boxes[:, 2:4] < min_size,
        min_size,
        candidate_boxes[:, 2:4],
    )
    return candidate_boxes


__all__ = ["assign_yolov8_obb_targets"]
