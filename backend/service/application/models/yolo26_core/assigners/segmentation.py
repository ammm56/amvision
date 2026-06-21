"""YOLO26 segmentation target assigner。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolo26_core.assigners.detection import (
    assign_yolo26_detection_targets,
    resolve_yolo26_tal_candidate_box_sizes,
)


@dataclass(frozen=True)
class Yolo26SegmentationAssignment:
    """描述单张图 YOLO26 segmentation loss 使用的 anchor 分配结果。"""

    batch_idx: Any
    class_ids: Any
    box_targets: Any
    box_scores: Any
    fg_mask: Any
    matched_gt_indices: Any | None = None
    mask_targets: Any | None = None
    mask_valid: Any | None = None


def assign_yolo26_segmentation_targets(
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
) -> Yolo26SegmentationAssignment | None:
    """根据当前图片 GT 和 anchor 生成 YOLO26 segmentation 正样本。"""

    device = prediction.device
    num_anchors = int(anchor_points.shape[0])
    boxes_list: list[Any] = []
    class_id_list: list[Any] = []
    for bbox, class_id in zip(targets["boxes"], targets["class_ids"], strict=True):
        boxes_list.append(bbox)
        class_id_list.append(class_id)
    if not boxes_list:
        return None

    gt_boxes = torch_module.tensor(boxes_list, dtype=prediction.dtype, device=device)
    gt_classes = torch_module.tensor(
        class_id_list, dtype=torch_module.long, device=device
    )
    gt_masks = targets.get("masks")
    gt_mask_valid = targets.get("mask_valid")
    if gt_masks is not None:
        gt_masks = gt_masks.to(device=device)
    if gt_mask_valid is not None:
        gt_mask_valid = gt_mask_valid.to(device=device)

    pred_boxes = _decode_yolo26_segmentation_prediction_boxes(
        torch_module=torch_module,
        prediction=prediction,
        anchor_points=anchor_points,
        stride_tensor=stride_tensor,
    )
    class_probabilities = prediction[:, 4 : 4 + int(num_classes)].sigmoid()
    anchor_centers_xy = anchor_points.to(
        device=device, dtype=prediction.dtype
    ) * stride_tensor.to(
        device=device,
        dtype=prediction.dtype,
    )
    candidate_min_box_size, candidate_replace_box_size = (
        resolve_yolo26_tal_candidate_box_sizes(stride_tensor=stride_tensor)
    )
    assignment = assign_yolo26_detection_targets(
        torch_module=torch_module,
        pred_boxes=pred_boxes.detach(),
        class_probabilities=class_probabilities.detach(),
        anchor_centers_xy=anchor_centers_xy,
        gt_boxes=gt_boxes,
        gt_classes=gt_classes,
        topk=topk,
        alpha=alpha,
        beta=beta,
        candidate_min_box_size=candidate_min_box_size,
        candidate_replace_box_size=candidate_replace_box_size,
    )
    foreground_mask = assignment["foreground_mask"]
    matched_gt_indices = assignment["assigned_gt_indices"].clamp_min(0)
    batch_idx = torch_module.zeros(num_anchors, dtype=torch_module.long, device=device)
    return Yolo26SegmentationAssignment(
        batch_idx=batch_idx,
        class_ids=gt_classes[matched_gt_indices],
        box_targets=gt_boxes[matched_gt_indices],
        box_scores=assignment["quality_scores"],
        fg_mask=foreground_mask,
        matched_gt_indices=assignment["assigned_gt_indices"],
        mask_targets=gt_masks,
        mask_valid=gt_mask_valid,
    )


def _decode_yolo26_segmentation_prediction_boxes(
    *,
    torch_module: Any,
    prediction: Any,
    anchor_points: Any,
    stride_tensor: Any,
) -> Any:
    """把 YOLO26 segmentation 训练预测距离解码为像素级 xyxy bbox。"""

    distances = prediction[:, :4]
    anchors = anchor_points.to(device=prediction.device, dtype=prediction.dtype)
    stride = stride_tensor.to(device=prediction.device, dtype=prediction.dtype)
    boxes = torch_module.cat(
        (
            anchors - distances[:, :2],
            anchors + distances[:, 2:4],
        ),
        dim=-1,
    )
    return boxes * stride.repeat(1, 4)
