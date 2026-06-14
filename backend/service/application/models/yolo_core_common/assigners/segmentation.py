"""YOLO segmentation target assigner。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SegmentationAssignment:
    """描述单张图 segmentation loss 使用的 anchor 分配结果。"""

    batch_idx: Any
    class_ids: Any
    box_targets: Any
    box_scores: Any
    fg_mask: Any
    matched_gt_indices: Any | None = None
    mask_targets: Any | None = None
    mask_valid: Any | None = None


def assign_segmentation_targets(
    *,
    torch_module: Any,
    targets: dict[str, Any],
    prediction: Any,
    anchor_points: Any,
    stride_tensor: Any,
    topk: int,
    alpha: float,
    beta: float,
    num_classes: int,
) -> SegmentationAssignment | None:
    """根据当前图片 GT 和 anchor 生成 segmentation 训练正样本。"""

    _ = alpha, beta, num_classes
    device = prediction.device
    num_anchors = int(anchor_points.shape[0])
    boxes_list: list[Any] = []
    class_id_list: list[Any] = []
    for bbox, class_id in zip(targets["boxes"], targets["class_ids"], strict=True):
        boxes_list.append(bbox)
        class_id_list.append(class_id)
    if not boxes_list:
        return None

    gt_boxes = torch_module.tensor(boxes_list, dtype=torch_module.float32, device=device)
    gt_classes = torch_module.tensor(class_id_list, dtype=torch_module.long, device=device)
    gt_masks = targets.get("masks")
    gt_mask_valid = targets.get("mask_valid")
    if gt_masks is not None:
        gt_masks = gt_masks.to(device=device)
    if gt_mask_valid is not None:
        gt_mask_valid = gt_mask_valid.to(device=device)

    gt_boxes_full = gt_boxes.unsqueeze(1).expand(-1, num_anchors, 4)
    anchor_boxes = torch_module.cat(
        [
            anchor_points - stride_tensor / 2,
            anchor_points + stride_tensor / 2,
        ],
        dim=-1,
    )
    anchor_boxes_expanded = anchor_boxes.unsqueeze(0).expand(
        gt_boxes.shape[0],
        -1,
        -1,
    )
    anchor_top_left = anchor_boxes_expanded[..., :2]
    anchor_bottom_right = anchor_boxes_expanded[..., 2:]
    gt_top_left = gt_boxes_full[..., :2]
    gt_bottom_right = gt_boxes_full[..., 2:]
    intersection_top_left = torch_module.maximum(anchor_top_left, gt_top_left)
    intersection_bottom_right = torch_module.minimum(anchor_bottom_right, gt_bottom_right)
    intersection_wh = (intersection_bottom_right - intersection_top_left).clamp(min=0)
    intersection_area = intersection_wh[..., 0] * intersection_wh[..., 1]
    anchor_area = (
        (anchor_bottom_right[..., 0] - anchor_top_left[..., 0])
        * (anchor_bottom_right[..., 1] - anchor_top_left[..., 1])
    )
    gt_area = (
        (gt_bottom_right[..., 0] - gt_top_left[..., 0])
        * (gt_bottom_right[..., 1] - gt_top_left[..., 1])
    )
    union_area = anchor_area + gt_area - intersection_area + 1e-16
    iou = intersection_area / union_area
    topk_values, topk_indices = torch_module.topk(iou, min(topk, iou.shape[1]), dim=1)
    dynamic_k = torch_module.clamp(topk_values.sum(dim=1).int(), min=1)
    foreground_mask = torch_module.zeros(
        num_anchors,
        dtype=torch_module.bool,
        device=device,
    )
    for gt_index in range(iou.shape[0]):
        foreground_mask[topk_indices[gt_index, : dynamic_k[gt_index]]] = True
    box_scores = (iou * foreground_mask.float().unsqueeze(0)).max(dim=0).values
    batch_idx = torch_module.zeros(num_anchors, dtype=torch_module.long, device=device)
    foreground_iou = iou * foreground_mask.float().unsqueeze(0)
    best_match = foreground_iou.argmax(dim=0)
    return SegmentationAssignment(
        batch_idx=batch_idx,
        class_ids=gt_classes[best_match],
        box_targets=gt_boxes[best_match],
        box_scores=box_scores,
        fg_mask=foreground_mask,
        matched_gt_indices=best_match,
        mask_targets=gt_masks,
        mask_valid=gt_mask_valid,
    )
