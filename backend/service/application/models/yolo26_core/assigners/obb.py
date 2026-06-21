"""YOLO26 OBB target assigner。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo26_core.targets import (
    yolo26_anchor_in_rotated_box,
    yolo26_xywhr_to_corners,
)


def assign_yolo26_obb_targets(
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
    replace_candidate_box_size: float | None = None,
    topk2: int | None = None,
) -> dict[str, Any]:
    """按 YOLO26 OBB 的 RotatedTaskAlignedAssigner 规则分配正样本。"""

    gt_count = int(gt_rboxes.shape[0])
    anchor_count = int(pred_rboxes.shape[0])
    if gt_count <= 0 or anchor_count <= 0:
        return {
            "foreground_mask": torch_module.zeros(
                anchor_count,
                dtype=torch_module.bool,
                device=pred_rboxes.device,
            ),
            "assigned_gt_indices": torch_module.full(
                (anchor_count,),
                -1,
                dtype=torch_module.long,
                device=pred_rboxes.device,
            ),
            "quality_scores": torch_module.zeros(
                anchor_count,
                dtype=pred_rboxes.dtype,
                device=pred_rboxes.device,
            ),
        }

    from backend.service.application.models.yolo26_core.losses.obb import (
        yolo26_probiou_aligned,
    )

    gt_expanded = gt_rboxes.unsqueeze(1).expand(-1, anchor_count, -1).reshape(-1, 5)
    pred_expanded = (
        pred_rboxes.detach().unsqueeze(0).expand(gt_count, -1, -1).reshape(-1, 5)
    )
    pair_iou = (
        yolo26_probiou_aligned(
            torch_module=torch_module,
            obb1=gt_expanded,
            obb2=pred_expanded,
        )
        .view(gt_count, anchor_count)
        .clamp(0.0, 1.0)
    )
    gt_class_probabilities = (
        class_probabilities.detach()[:, gt_classes].t().clamp(0.0, 1.0)
    )
    alignment_metric = gt_class_probabilities.pow(alpha) * pair_iou.pow(beta)

    candidate_gt_rboxes = _build_yolo26_obb_candidate_boxes(
        torch_module=torch_module,
        gt_rboxes=gt_rboxes,
        min_candidate_box_size=min_candidate_box_size,
        replace_candidate_box_size=replace_candidate_box_size,
    )
    inside_mask = yolo26_anchor_in_rotated_box(
        torch_module=torch_module,
        anchor_points=anchor_centers_xy,
        corners=yolo26_xywhr_to_corners(
            torch_module=torch_module,
            rboxes=candidate_gt_rboxes,
        ),
    )
    alignment_metric = alignment_metric * inside_mask.to(alignment_metric.dtype)
    candidate_mask = _select_yolo26_obb_candidates(
        torch_module=torch_module,
        alignment_metric=alignment_metric,
        gt_rboxes=candidate_gt_rboxes,
        anchor_centers_xy=anchor_centers_xy,
        topk=topk,
        topk2=topk2,
        gt_count=gt_count,
        anchor_count=anchor_count,
    )
    matched_metric = alignment_metric * candidate_mask.to(alignment_metric.dtype)
    matched_iou = pair_iou * candidate_mask.to(pair_iou.dtype)
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
        "matched_metric": matched_metric,
    }


def _select_yolo26_obb_candidates(
    *,
    torch_module: Any,
    alignment_metric: Any,
    gt_rboxes: Any,
    anchor_centers_xy: Any,
    topk: int,
    topk2: int | None,
    gt_count: int,
    anchor_count: int,
) -> Any:
    """选择 YOLO26 OBB TAL 候选 anchor。"""

    candidate_mask = torch_module.zeros(
        (gt_count, anchor_count),
        dtype=torch_module.bool,
        device=alignment_metric.device,
    )
    topk_count = min(max(1, int(topk)), anchor_count)
    for gt_index in range(gt_count):
        valid_indices = torch_module.nonzero(
            alignment_metric[gt_index] > 0,
            as_tuple=False,
        ).squeeze(1)
        if int(valid_indices.numel()) == 0:
            continue
        selected_count = min(topk_count, int(valid_indices.numel()))
        _, topk_indices = torch_module.topk(
            alignment_metric[gt_index][valid_indices],
            k=selected_count,
        )
        candidate_mask[gt_index, valid_indices[topk_indices]] = True

    if topk2 is None or int(topk2) == int(topk):
        return candidate_mask
    return _refine_yolo26_obb_candidate_mask(
        torch_module=torch_module,
        candidate_mask=candidate_mask,
        alignment_metric=alignment_metric,
        topk2=int(topk2),
        anchor_count=anchor_count,
    )


def _refine_yolo26_obb_candidate_mask(
    *,
    torch_module: Any,
    candidate_mask: Any,
    alignment_metric: Any,
    topk2: int,
    anchor_count: int,
) -> Any:
    """对 YOLO26 OBB 初始 topk 候选执行二次精选。"""

    refined_metric = alignment_metric * candidate_mask.to(alignment_metric.dtype)
    refined_mask = torch_module.zeros_like(candidate_mask)
    refined_count = min(max(1, topk2), anchor_count)
    for gt_index in range(int(candidate_mask.shape[0])):
        valid_indices = torch_module.nonzero(
            refined_metric[gt_index] > 0,
            as_tuple=False,
        ).squeeze(1)
        if int(valid_indices.numel()) == 0:
            continue
        selected_count = min(refined_count, int(valid_indices.numel()))
        _, topk_indices = torch_module.topk(
            refined_metric[gt_index][valid_indices],
            k=selected_count,
        )
        refined_mask[gt_index, valid_indices[topk_indices]] = True
    return refined_mask


def _build_yolo26_obb_candidate_boxes(
    *,
    torch_module: Any,
    gt_rboxes: Any,
    min_candidate_box_size: float,
    replace_candidate_box_size: float | None,
) -> Any:
    """构造 YOLO26 OBB 正样本筛选使用的最小尺寸旋转框。"""

    if min_candidate_box_size <= 0:
        return gt_rboxes
    min_size = gt_rboxes.new_tensor(float(min_candidate_box_size))
    replace_size = gt_rboxes.new_tensor(
        float(
            replace_candidate_box_size
            if replace_candidate_box_size is not None
            else min_candidate_box_size
        )
    )
    candidate_boxes = gt_rboxes.clone()
    candidate_boxes[:, 2:4] = torch_module.where(
        candidate_boxes[:, 2:4] < min_size,
        replace_size,
        candidate_boxes[:, 2:4],
    )
    return candidate_boxes


__all__ = ["assign_yolo26_obb_targets"]
