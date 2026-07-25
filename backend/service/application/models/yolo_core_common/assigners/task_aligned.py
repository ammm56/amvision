"""YOLOv8/11/26 共用 Task-Aligned Assignment 收尾逻辑。"""

from __future__ import annotations

from typing import Any


def finalize_task_aligned_assignment(
    *,
    torch_module: Any,
    candidate_mask: Any,
    alignment_metric: Any,
    overlaps: Any,
    topk: int,
    topk2: int | None,
    eps: float = 1e-9,
) -> dict[str, Any]:
    """按 Ultralytics 顺序完成多 GT 冲突消解、二次筛选和 score 归一化。"""

    num_gt, num_anchors = candidate_mask.shape
    foreground_counts = candidate_mask.sum(dim=0)
    if bool((foreground_counts > 1).any()):
        multi_gt_mask = (foreground_counts > 1).unsqueeze(0).expand(
            num_gt,
            num_anchors,
        )
        highest_overlap_indices = overlaps.argmax(dim=0)
        highest_overlap_mask = torch_module.zeros_like(candidate_mask)
        highest_overlap_mask.scatter_(
            0,
            highest_overlap_indices.unsqueeze(0),
            True,
        )
        candidate_mask = torch_module.where(
            multi_gt_mask,
            highest_overlap_mask,
            candidate_mask,
        )

    if topk2 is not None and topk2 != topk:
        refined_count = min(max(1, int(topk2)), int(num_anchors))
        masked_alignment = alignment_metric * candidate_mask.to(
            alignment_metric.dtype
        )
        refined_indices = torch_module.topk(
            masked_alignment,
            k=refined_count,
            dim=-1,
            largest=True,
        ).indices
        refined_mask = torch_module.zeros_like(candidate_mask)
        refined_mask.scatter_(-1, refined_indices, True)
        candidate_mask = candidate_mask & refined_mask

    foreground_mask = candidate_mask.any(dim=0)
    assigned_gt_indices = candidate_mask.to(alignment_metric.dtype).argmax(dim=0)
    assigned_gt_indices = assigned_gt_indices.to(dtype=torch_module.long).where(
        foreground_mask,
        torch_module.full_like(assigned_gt_indices, -1),
    )

    candidate_weight = candidate_mask.to(alignment_metric.dtype)
    masked_alignment = alignment_metric * candidate_weight
    masked_overlaps = overlaps * candidate_weight
    max_alignment_per_gt = masked_alignment.amax(dim=-1, keepdim=True)
    max_overlap_per_gt = masked_overlaps.amax(dim=-1, keepdim=True)
    normalized_alignment = (
        masked_alignment
        * max_overlap_per_gt
        / (max_alignment_per_gt + float(eps))
    )
    quality_scores = normalized_alignment.amax(dim=0).where(
        foreground_mask,
        torch_module.zeros_like(foreground_mask, dtype=alignment_metric.dtype),
    )
    return {
        "foreground_mask": foreground_mask,
        "assigned_gt_indices": assigned_gt_indices,
        "quality_scores": quality_scores.clamp(0.0, 1.0),
        "candidate_mask": candidate_mask,
    }
