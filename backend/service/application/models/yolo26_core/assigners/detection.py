"""YOLO26 detection target assigner。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.assigners.task_aligned import (
    finalize_task_aligned_assignment,
)
from backend.service.application.models.yolo_core_common.losses.box import (
    bbox_ciou_matrix,
)


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
    candidate_min_box_size: float = 0.0,
    candidate_replace_box_size: float | None = None,
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

    candidate_gt_boxes = _build_yolo26_candidate_boxes(
        torch_module=torch_module,
        gt_boxes=gt_boxes,
        min_box_size=candidate_min_box_size,
        replace_box_size=candidate_replace_box_size,
    )
    inside_mask = _build_yolo26_anchor_inside_mask(
        torch_module=torch_module,
        anchor_centers_xy=anchor_centers_xy,
        gt_boxes=candidate_gt_boxes,
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
    candidate_count = min(max(1, topk), num_anchors)

    for gt_index in range(num_gt):
        gt_metric = alignment_metric[gt_index]
        topk_count = min(candidate_count, int(gt_metric.numel()))
        _, topk_indices = torch_module.topk(gt_metric, k=topk_count)
        candidate_mask[gt_index, topk_indices] = True

    candidate_mask = candidate_mask & inside_mask
    assignment = finalize_task_aligned_assignment(
        torch_module=torch_module,
        candidate_mask=candidate_mask,
        alignment_metric=alignment_metric,
        overlaps=pair_iou,
        topk=topk,
        topk2=topk2,
    )
    return {
        "foreground_mask": assignment["foreground_mask"],
        "assigned_gt_indices": assignment["assigned_gt_indices"],
        "quality_scores": assignment["quality_scores"],
    }


def resolve_yolo26_tal_candidate_box_sizes(
    *,
    stride_tensor: Any,
) -> tuple[float, float]:
    """从 stride tensor 解析 YOLO26 TAL tiny box 候选尺寸规则。"""

    values = stride_tensor.detach().reshape(-1).unique().sort().values
    if int(values.numel()) == 0:
        return 0.0, 0.0
    min_box_size = float(values[0].item())
    replace_box_size = (
        float(values[1].item()) if int(values.numel()) > 1 else min_box_size
    )
    return min_box_size, replace_box_size


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
    """按 Ultralytics xyxy bbox 规则计算 CIoU 矩阵。"""

    return bbox_ciou_matrix(
        torch_module=torch_module,
        boxes1=boxes1,
        boxes2=boxes2,
    )


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


def _build_yolo26_candidate_boxes(
    *,
    torch_module: Any,
    gt_boxes: Any,
    min_box_size: float,
    replace_box_size: float | None,
) -> Any:
    """按 Ultralytics TAL 规则扩张 tiny bbox 候选筛选范围。"""

    if min_box_size <= 0:
        return gt_boxes
    min_size = gt_boxes.new_tensor(float(min_box_size))
    replacement = gt_boxes.new_tensor(
        float(replace_box_size if replace_box_size is not None else min_box_size)
    )
    center_xy = (gt_boxes[:, 0:2] + gt_boxes[:, 2:4]) * 0.5
    wh = (gt_boxes[:, 2:4] - gt_boxes[:, 0:2]).clamp_min(0.0)
    candidate_wh = torch_module.where(wh < min_size, replacement, wh)
    half_wh = candidate_wh * 0.5
    return torch_module.cat((center_xy - half_wh, center_xy + half_wh), dim=1)
