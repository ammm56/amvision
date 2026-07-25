"""YOLOv8 detection target assigner。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.assigners.task_aligned import (
    finalize_task_aligned_assignment,
)
from backend.service.application.models.yolo_core_common.losses.box import (
    bbox_ciou_matrix,
)


def assign_yolov8_detection_targets(
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
    min_stride: float = 8.0,
    tiny_box_stride: float = 16.0,
) -> dict[str, Any]:
    """按 YOLOv8 detection task-aligned 规则分配正样本 anchor。"""

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

    inside_mask = _build_yolov8_anchor_inside_mask(
        torch_module=torch_module,
        anchor_centers_xy=anchor_centers_xy,
        gt_boxes=gt_boxes,
        min_stride=min_stride,
        tiny_box_stride=tiny_box_stride,
    )
    pair_iou = yolov8_box_iou_matrix(
        torch_module=torch_module,
        boxes1=gt_boxes,
        boxes2=pred_boxes,
    ).clamp(0.0, 1.0)
    gt_class_probabilities = class_probabilities[:, gt_classes].transpose(0, 1).clamp(0.0, 1.0)
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


def yolov8_box_iou_matrix(
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
    return _yolov8_box_ciou_matrix(torch_module=torch_module, boxes1=boxes1, boxes2=boxes2)


def yolov8_box_iou_aligned(
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
    ciou = _yolov8_box_ciou_matrix(
        torch_module=torch_module,
        boxes1=boxes1,
        boxes2=boxes2,
    )
    return ciou.diagonal()


def _yolov8_box_ciou_matrix(
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


def _build_yolov8_anchor_inside_mask(
    *,
    torch_module: Any,
    anchor_centers_xy: Any,
    gt_boxes: Any,
    min_stride: float,
    tiny_box_stride: float,
) -> Any:
    """判断 anchor center 是否落在 gt bbox 内部，并按 Ultralytics 规则扩展 tiny bbox。"""

    gt_boxes = _expand_yolov8_tiny_gt_boxes_for_assignment(
        torch_module=torch_module,
        gt_boxes=gt_boxes,
        min_stride=min_stride,
        tiny_box_stride=tiny_box_stride,
    )
    center_x = anchor_centers_xy[:, 0].unsqueeze(0)
    center_y = anchor_centers_xy[:, 1].unsqueeze(0)
    return (
        (center_x >= gt_boxes[:, 0:1])
        & (center_x <= gt_boxes[:, 2:3])
        & (center_y >= gt_boxes[:, 1:2])
        & (center_y <= gt_boxes[:, 3:4])
    )


def _expand_yolov8_tiny_gt_boxes_for_assignment(
    *,
    torch_module: Any,
    gt_boxes: Any,
    min_stride: float,
    tiny_box_stride: float,
) -> Any:
    """按 Ultralytics TAL 规则把小于最小 stride 的 gt bbox 扩到稳定候选范围。"""

    centers = (gt_boxes[:, 0:2] + gt_boxes[:, 2:4]) * 0.5
    sizes = (gt_boxes[:, 2:4] - gt_boxes[:, 0:2]).clamp_min(0.0)
    tiny_mask = sizes < float(min_stride)
    if not bool(tiny_mask.any()):
        return gt_boxes

    expanded_sizes = torch_module.where(
        tiny_mask,
        torch_module.full_like(sizes, float(tiny_box_stride)),
        sizes,
    )
    half_sizes = expanded_sizes * 0.5
    return torch_module.cat((centers - half_sizes, centers + half_sizes), dim=1)
