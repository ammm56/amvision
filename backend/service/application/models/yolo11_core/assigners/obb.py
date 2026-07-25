"""YOLO11 OBB target assigner。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.assigners.task_aligned import (
    finalize_task_aligned_assignment,
)
from backend.service.application.models.yolo11_core.targets import (
    yolo11_anchor_in_rotated_box,
    yolo11_xywhr_to_corners,
)


def assign_yolo11_obb_targets(
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
    topk2: int | None = None,
) -> dict[str, Any]:
    """按 YOLO11 OBB 的 RotatedTaskAlignedAssigner 规则分配正样本。"""

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

    from backend.service.application.models.yolo11_core.losses.obb import (
        yolo11_probiou_aligned,
    )

    gt_expanded = gt_rboxes.unsqueeze(1).expand(-1, anchor_count, -1).reshape(-1, 5)
    pred_expanded = (
        pred_rboxes.detach().unsqueeze(0).expand(gt_count, -1, -1).reshape(-1, 5)
    )
    pair_iou = (
        yolo11_probiou_aligned(
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

    candidate_gt_rboxes = _build_yolo11_obb_candidate_boxes(
        torch_module=torch_module,
        gt_rboxes=gt_rboxes,
        min_candidate_box_size=min_candidate_box_size,
    )
    inside_mask = yolo11_anchor_in_rotated_box(
        torch_module=torch_module,
        anchor_points=anchor_centers_xy,
        corners=yolo11_xywhr_to_corners(
            torch_module=torch_module,
            rboxes=candidate_gt_rboxes,
        ),
    )
    alignment_metric = alignment_metric * inside_mask.to(alignment_metric.dtype)
    candidate_mask = _select_yolo11_obb_candidates(
        torch_module=torch_module,
        alignment_metric=alignment_metric,
        inside_mask=inside_mask,
        gt_rboxes=candidate_gt_rboxes,
        anchor_centers_xy=anchor_centers_xy,
        topk=topk,
        gt_count=gt_count,
        anchor_count=anchor_count,
    )
    assignment = finalize_task_aligned_assignment(
        torch_module=torch_module,
        candidate_mask=candidate_mask,
        alignment_metric=alignment_metric,
        overlaps=pair_iou,
        topk=topk,
        topk2=topk2,
    )
    matched_metric = (
        alignment_metric
        * assignment["candidate_mask"].to(alignment_metric.dtype)
    )
    return {
        "foreground_mask": assignment["foreground_mask"],
        "assigned_gt_indices": assignment["assigned_gt_indices"],
        "quality_scores": assignment["quality_scores"],
        "matched_metric": matched_metric,
    }


def _select_yolo11_obb_candidates(
    *,
    torch_module: Any,
    alignment_metric: Any,
    inside_mask: Any,
    gt_rboxes: Any,
    anchor_centers_xy: Any,
    topk: int,
    gt_count: int,
    anchor_count: int,
) -> Any:
    """选择 YOLO11 OBB TAL 候选 anchor。"""

    candidate_mask = torch_module.zeros(
        (gt_count, anchor_count),
        dtype=torch_module.bool,
        device=alignment_metric.device,
    )
    topk_count = min(max(1, int(topk)), anchor_count)
    for gt_index in range(gt_count):
        selected_count = min(topk_count, int(alignment_metric[gt_index].numel()))
        _, topk_indices = torch_module.topk(
            alignment_metric[gt_index],
            k=selected_count,
        )
        candidate_mask[gt_index, topk_indices] = True

    return candidate_mask & inside_mask


def _build_yolo11_obb_candidate_boxes(
    *,
    torch_module: Any,
    gt_rboxes: Any,
    min_candidate_box_size: float,
) -> Any:
    """构造 YOLO11 OBB 正样本筛选使用的最小尺寸旋转框。"""

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


__all__ = ["assign_yolo11_obb_targets"]
