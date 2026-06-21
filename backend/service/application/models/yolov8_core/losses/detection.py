"""YOLOv8 detection loss。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolov8_core.decode import (
    decode_yolov8_detection_training_predictions,
)
from backend.service.application.models.yolov8_core.assigners import (
    assign_yolov8_detection_targets,
    yolov8_box_iou_aligned,
)
from backend.service.application.models.yolov8_core.targets import (
    yolov8_bbox_xyxy_to_distances,
)


def compute_yolov8_detection_loss(
    *,
    torch_module: Any,
    detect_head: Any,
    raw_outputs: dict[str, Any],
    batch_targets: tuple[Any, ...],
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    assign_topk2: int | None = None,
) -> dict[str, Any]:
    """按 YOLOv8 detection 规则计算分类、框回归和 DFL 损失。"""

    prediction_bundle = decode_yolov8_detection_training_predictions(
        torch_module=torch_module,
        detect_head=detect_head,
        raw_outputs=raw_outputs,
    )
    class_logits = prediction_bundle["class_logits"]
    class_probabilities = class_logits.sigmoid()
    pred_boxes = prediction_bundle["boxes_xyxy"]
    distance_logits = prediction_bundle["distance_logits"]
    anchor_points = prediction_bundle["anchor_points"]
    stride_tensor = prediction_bundle["stride_tensor"]
    anchor_centers_xy = prediction_bundle["anchor_centers_xy"]
    reg_max = int(prediction_bundle["reg_max"])

    total_class_loss = class_logits.new_zeros(())
    total_box_loss = class_logits.new_zeros(())
    total_dfl_loss = class_logits.new_zeros(())
    total_target_score = class_logits.new_zeros(())

    for batch_index, target in enumerate(batch_targets):
        image_class_logits = class_logits[batch_index]
        image_class_probabilities = class_probabilities[batch_index]
        image_pred_boxes = pred_boxes[batch_index]
        target_scores = torch_module.zeros_like(image_class_logits)

        if target.boxes_xyxy:
            loss_state = _compute_yolov8_image_detection_loss(
                torch_module=torch_module,
                image_class_probabilities=image_class_probabilities,
                image_pred_boxes=image_pred_boxes,
                target=target,
                target_scores=target_scores,
                anchor_centers_xy=anchor_centers_xy,
                anchor_points=anchor_points,
                stride_tensor=stride_tensor,
                distance_logits=distance_logits[batch_index],
                reg_max=reg_max,
                assign_topk=assign_topk,
                assign_alpha=assign_alpha,
                assign_beta=assign_beta,
                assign_topk2=assign_topk2,
            )
            total_box_loss = total_box_loss + loss_state["box_loss"]
            total_dfl_loss = total_dfl_loss + loss_state["dfl_loss"]
            total_target_score = total_target_score + loss_state["target_score"]

        total_class_loss = total_class_loss + torch_module.nn.functional.binary_cross_entropy_with_logits(
            image_class_logits,
            target_scores,
            reduction="sum",
        )

    normalizer = total_target_score.clamp_min(1.0)
    class_loss = total_class_loss / normalizer
    box_loss = total_box_loss / normalizer
    dfl_loss = total_dfl_loss / normalizer
    total_loss = (
        class_loss * class_loss_weight
        + box_loss * box_loss_weight
        + dfl_loss * dfl_loss_weight
    )
    return {
        "loss": total_loss,
        "class_loss": class_loss,
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
    }


def yolov8_distribution_focal_loss(
    *,
    torch_module: Any,
    logits: Any,
    target: Any,
) -> Any:
    """计算 YOLOv8 DFL 损失。"""

    reg_max = int(logits.shape[2])
    target_left = target.clamp(0, reg_max - 1 - 0.01).floor().long()
    target_right = (target_left + 1).clamp(0, reg_max - 1)
    weight_left = target_right.to(target.dtype) - target
    weight_right = 1.0 - weight_left
    flat_logits = logits.reshape(-1, reg_max)
    loss_left = torch_module.nn.functional.cross_entropy(
        flat_logits,
        target_left.reshape(-1),
        reduction="none",
    )
    loss_right = torch_module.nn.functional.cross_entropy(
        flat_logits,
        target_right.reshape(-1),
        reduction="none",
    )
    combined = loss_left * weight_left.reshape(-1) + loss_right * weight_right.reshape(-1)
    return combined.view(-1, 4).mean(dim=1)


def _compute_yolov8_image_detection_loss(
    *,
    torch_module: Any,
    image_class_probabilities: Any,
    image_pred_boxes: Any,
    target: Any,
    target_scores: Any,
    anchor_centers_xy: Any,
    anchor_points: Any,
    stride_tensor: Any,
    distance_logits: Any,
    reg_max: int,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    assign_topk2: int | None,
) -> dict[str, Any]:
    """计算单张图片的 YOLOv8 detection 正样本损失。"""

    gt_boxes = torch_module.tensor(
        target.boxes_xyxy,
        device=image_pred_boxes.device,
        dtype=image_pred_boxes.dtype,
    )
    gt_classes = torch_module.tensor(
        target.category_indexes,
        device=image_pred_boxes.device,
        dtype=torch_module.long,
    )
    with torch_module.no_grad():
        assignment = assign_yolov8_detection_targets(
            torch_module=torch_module,
            pred_boxes=image_pred_boxes.detach(),
            class_probabilities=image_class_probabilities.detach(),
            anchor_centers_xy=anchor_centers_xy,
            gt_boxes=gt_boxes,
            gt_classes=gt_classes,
            topk=assign_topk,
            alpha=assign_alpha,
            beta=assign_beta,
            topk2=assign_topk2,
        )

    foreground_mask = assignment["foreground_mask"]
    if int(foreground_mask.sum().item()) <= 0:
        return {
            "box_loss": image_pred_boxes.new_zeros(()),
            "dfl_loss": image_pred_boxes.new_zeros(()),
            "foreground_count": 0,
            "target_score": image_pred_boxes.new_zeros(()),
        }

    assigned_gt_indices = assignment["assigned_gt_indices"][foreground_mask]
    quality_scores = assignment["quality_scores"][foreground_mask]
    target_scores[foreground_mask, gt_classes[assigned_gt_indices]] = quality_scores

    foreground_pred_boxes = image_pred_boxes[foreground_mask]
    foreground_gt_boxes = gt_boxes[assigned_gt_indices]
    iou_values = yolov8_box_iou_aligned(
        torch_module=torch_module,
        boxes1=foreground_pred_boxes,
        boxes2=foreground_gt_boxes,
    ).clamp(0.0, 1.0)
    box_loss = ((1.0 - iou_values) * quality_scores).sum()
    target_score = quality_scores.sum()

    target_distances = yolov8_bbox_xyxy_to_distances(
        torch_module=torch_module,
        boxes_xyxy=foreground_gt_boxes,
        anchor_points=anchor_points[foreground_mask],
        stride_tensor=stride_tensor[foreground_mask],
        reg_max=reg_max,
    )
    if reg_max > 1:
        foreground_distance_logits = distance_logits[foreground_mask].view(-1, 4, reg_max)
        dfl_loss = yolov8_distribution_focal_loss(
            torch_module=torch_module,
            logits=foreground_distance_logits,
            target=target_distances,
        )
        dfl_loss = (dfl_loss * quality_scores).sum()
    else:
        foreground_distance_logits = distance_logits[foreground_mask].view(-1, 4)
        dfl_loss = torch_module.nn.functional.smooth_l1_loss(
            torch_module.nn.functional.softplus(foreground_distance_logits),
            target_distances,
            reduction="none",
        )
        dfl_loss = (dfl_loss.mean(dim=1) * quality_scores).sum()

    return {
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
        "foreground_count": int(foreground_mask.sum().item()),
        "target_score": target_score,
    }
