"""YOLO11 pose loss。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo11_core.assigners import (
    assign_yolo11_pose_targets,
    yolo11_pose_box_iou_aligned,
)
from backend.service.application.models.yolo11_core.decode import (
    decode_yolo11_detection_training_predictions,
)
from backend.service.application.models.yolo11_core.losses.detection import (
    yolo11_distribution_focal_loss,
)
from backend.service.application.models.yolo11_core.targets import (
    normalize_yolo11_gt_keypoints_tensor,
    yolo11_bbox_xyxy_to_distances,
)
from backend.service.application.models.yolo_core_common.losses.pose import (
    build_pose_box_area,
    build_pose_oks_sigmas,
    build_pose_visibility_mask,
    compute_oks_keypoint_loss,
    compute_visibility_loss,
)


def compute_yolo11_pose_loss(
    *,
    torch: Any,
    model: Any,
    raw_outputs: dict[str, Any],
    batch_targets: tuple[Any, ...],
    num_classes: int,
    kpt_shape: tuple[int, int] = (17, 3),
    class_loss_weight: float = 0.5,
    box_loss_weight: float = 7.5,
    dfl_loss_weight: float = 1.5,
    kpt_loss_weight: float = 12.0,
    visibility_loss_weight: float = 1.0,
    assign_topk: int = 10,
    assign_alpha: float = 0.5,
    assign_beta: float = 6.0,
    assign_topk2: int | None = None,
) -> dict[str, Any]:
    """计算 YOLO11 pose 的 box、class、DFL、keypoint 和可见性损失。"""

    _ = num_classes
    pose_head = model.model[-1]
    keypoint_count = int(kpt_shape[0])
    keypoint_dim = int(kpt_shape[1])

    prediction_bundle = decode_yolo11_detection_training_predictions(
        torch_module=torch,
        detect_head=pose_head,
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

    raw_keypoints = raw_outputs.get("kpts")
    pred_keypoints = (
        raw_keypoints.permute(0, 2, 1).contiguous()
        if raw_keypoints is not None
        else None
    )

    batch_size = int(class_logits.shape[0])
    total_class_loss = class_logits.new_zeros(())
    total_box_loss = class_logits.new_zeros(())
    total_dfl_loss = class_logits.new_zeros(())
    total_keypoint_loss = class_logits.new_zeros(())
    total_visibility_loss = class_logits.new_zeros(())
    total_foreground = 0
    total_target_score = class_logits.new_zeros(())

    for batch_index in range(batch_size):
        loss_state = _compute_yolo11_pose_image_loss(
            torch_module=torch,
            batch_index=batch_index,
            image_class_logits=class_logits[batch_index],
            image_class_probabilities=class_probabilities[batch_index],
            image_pred_boxes=pred_boxes[batch_index],
            target=batch_targets[batch_index],
            anchor_centers_xy=anchor_centers_xy,
            anchor_points=anchor_points,
            stride_tensor=stride_tensor,
            distance_logits=distance_logits[batch_index],
            reg_max=reg_max,
            pred_keypoints=pred_keypoints,
            keypoint_count=keypoint_count,
            keypoint_dim=keypoint_dim,
            assign_topk=assign_topk,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            assign_topk2=assign_topk2,
        )
        total_class_loss = total_class_loss + loss_state["class_loss"]
        total_box_loss = total_box_loss + loss_state["box_loss"]
        total_dfl_loss = total_dfl_loss + loss_state["dfl_loss"]
        total_keypoint_loss = total_keypoint_loss + loss_state["keypoint_loss"]
        total_visibility_loss = total_visibility_loss + loss_state["visibility_loss"]
        total_target_score = total_target_score + loss_state["target_score"]
        total_foreground += int(loss_state["foreground_count"])

    normalizer = total_target_score.clamp_min(1.0)
    foreground_normalizer = max(total_foreground, 1)
    class_loss = total_class_loss / normalizer
    box_loss = total_box_loss / normalizer
    dfl_loss = total_dfl_loss / normalizer
    keypoint_loss = total_keypoint_loss / foreground_normalizer
    visibility_loss = total_visibility_loss / foreground_normalizer
    total_loss = (
        class_loss * class_loss_weight
        + box_loss * box_loss_weight
        + dfl_loss * dfl_loss_weight
        + keypoint_loss * kpt_loss_weight
        + visibility_loss * visibility_loss_weight
    )
    return {
        "loss": total_loss,
        "class_loss": class_loss,
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
        "kpt_loss": keypoint_loss,
        "visibility_loss": visibility_loss,
    }


def _compute_yolo11_pose_image_loss(
    *,
    torch_module: Any,
    batch_index: int,
    image_class_logits: Any,
    image_class_probabilities: Any,
    image_pred_boxes: Any,
    target: Any,
    anchor_centers_xy: Any,
    anchor_points: Any,
    stride_tensor: Any,
    distance_logits: Any,
    reg_max: int,
    pred_keypoints: Any | None,
    keypoint_count: int,
    keypoint_dim: int,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    assign_topk2: int | None,
) -> dict[str, Any]:
    """计算单张图片的 YOLO11 pose 训练损失。"""

    target_scores = torch_module.zeros_like(image_class_logits)
    zero_loss = image_class_logits.new_zeros(())
    gt_boxes_list = getattr(target, "boxes_xyxy", None) or getattr(
        target, "boxes", None
    )
    gt_classes_list = getattr(target, "category_indexes", None) or getattr(
        target, "class_ids", None
    )
    gt_keypoints = getattr(target, "keypoints", None)

    if gt_boxes_list is None or len(gt_boxes_list) == 0:
        return {
            "class_loss": torch_module.nn.functional.binary_cross_entropy_with_logits(
                image_class_logits,
                target_scores,
                reduction="sum",
            ),
            "box_loss": zero_loss,
            "dfl_loss": zero_loss,
            "keypoint_loss": zero_loss,
            "visibility_loss": zero_loss,
            "foreground_count": 0,
            "target_score": zero_loss,
        }

    gt_boxes = torch_module.tensor(
        gt_boxes_list,
        device=image_pred_boxes.device,
        dtype=image_pred_boxes.dtype,
    )
    gt_classes = torch_module.tensor(
        gt_classes_list,
        device=image_pred_boxes.device,
        dtype=torch_module.long,
    )
    with torch_module.no_grad():
        assignment = assign_yolo11_pose_targets(
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
    foreground_count = int(foreground_mask.sum().item())
    if foreground_count <= 0:
        return {
            "class_loss": torch_module.nn.functional.binary_cross_entropy_with_logits(
                image_class_logits,
                target_scores,
                reduction="sum",
            ),
            "box_loss": zero_loss,
            "dfl_loss": zero_loss,
            "keypoint_loss": zero_loss,
            "visibility_loss": zero_loss,
            "foreground_count": 0,
            "target_score": zero_loss,
        }

    assigned_indices = assignment["assigned_gt_indices"][foreground_mask]
    quality_scores = assignment["quality_scores"][foreground_mask]
    target_scores[foreground_mask, gt_classes[assigned_indices]] = quality_scores
    foreground_pred_boxes = image_pred_boxes[foreground_mask]
    foreground_gt_boxes = gt_boxes[assigned_indices]
    iou_values = yolo11_pose_box_iou_aligned(
        torch_module=torch_module,
        boxes1=foreground_pred_boxes,
        boxes2=foreground_gt_boxes,
    ).clamp(0.0, 1.0)
    box_loss = ((1.0 - iou_values) * quality_scores).sum()
    dfl_loss = _compute_yolo11_pose_dfl_loss(
        torch_module=torch_module,
        distance_logits=distance_logits,
        foreground_mask=foreground_mask,
        foreground_gt_boxes=foreground_gt_boxes,
        foreground_anchor_points=anchor_points[foreground_mask],
        foreground_stride=stride_tensor[foreground_mask],
        quality_scores=quality_scores,
        reg_max=reg_max,
    )
    keypoint_loss = zero_loss
    visibility_loss = zero_loss
    if (
        pred_keypoints is not None
        and gt_keypoints is not None
        and len(gt_keypoints) > 0
    ):
        keypoint_loss, visibility_loss = _compute_yolo11_pose_keypoint_losses(
            torch_module=torch_module,
            pred_keypoints=pred_keypoints,
            batch_index=batch_index,
            foreground_mask=foreground_mask,
            assigned_indices=assigned_indices,
            gt_keypoints=gt_keypoints,
            keypoint_count=keypoint_count,
            keypoint_dim=keypoint_dim,
            foreground_anchor_points=anchor_points[foreground_mask],
            foreground_stride=stride_tensor[foreground_mask],
            foreground_gt_boxes=foreground_gt_boxes,
        )

    class_loss = torch_module.nn.functional.binary_cross_entropy_with_logits(
        image_class_logits,
        target_scores,
        reduction="sum",
    )
    return {
        "class_loss": class_loss,
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
        "keypoint_loss": keypoint_loss * foreground_count,
        "visibility_loss": visibility_loss * foreground_count,
        "foreground_count": foreground_count,
        "target_score": quality_scores.sum(),
    }


def _compute_yolo11_pose_dfl_loss(
    *,
    torch_module: Any,
    distance_logits: Any,
    foreground_mask: Any,
    foreground_gt_boxes: Any,
    foreground_anchor_points: Any,
    foreground_stride: Any,
    quality_scores: Any,
    reg_max: int,
) -> Any:
    """计算 YOLO11 pose DFL 分量。"""

    target_distances = yolo11_bbox_xyxy_to_distances(
        torch_module=torch_module,
        boxes_xyxy=foreground_gt_boxes,
        anchor_points=foreground_anchor_points,
        stride_tensor=foreground_stride,
        reg_max=reg_max,
    )
    if reg_max > 1:
        foreground_distance_logits = distance_logits[foreground_mask].view(
            -1, 4, reg_max
        )
        dfl_loss = yolo11_distribution_focal_loss(
            torch_module=torch_module,
            logits=foreground_distance_logits,
            target=target_distances,
        )
        return (dfl_loss * quality_scores).sum()
    foreground_distance_logits = distance_logits[foreground_mask].view(-1, 4)
    dfl_loss = torch_module.nn.functional.smooth_l1_loss(
        torch_module.nn.functional.softplus(foreground_distance_logits),
        target_distances,
        reduction="none",
    )
    return (dfl_loss.mean(dim=1) * quality_scores).sum()


def _compute_yolo11_pose_keypoint_losses(
    *,
    torch_module: Any,
    pred_keypoints: Any,
    batch_index: int,
    foreground_mask: Any,
    assigned_indices: Any,
    gt_keypoints: Any,
    keypoint_count: int,
    keypoint_dim: int,
    foreground_anchor_points: Any,
    foreground_stride: Any,
    foreground_gt_boxes: Any,
) -> tuple[Any, Any]:
    """计算 YOLO11 pose 关键点位置和可见性损失。"""

    foreground_pred_keypoints = pred_keypoints[batch_index][foreground_mask]
    foreground_gt_keypoints = normalize_yolo11_gt_keypoints_tensor(
        torch_module=torch_module,
        raw_keypoints=gt_keypoints,
        assigned_indices=assigned_indices,
        num_keypoints=keypoint_count,
        keypoint_dim=keypoint_dim,
        device=foreground_pred_keypoints.device,
        dtype=foreground_pred_keypoints.dtype,
    )
    foreground_count = int(foreground_pred_keypoints.shape[0])
    pred_keypoints_reshaped = foreground_pred_keypoints.view(
        foreground_count,
        keypoint_count,
        keypoint_dim,
    )
    stride_values = foreground_stride.view(-1, 1)
    decoded_keypoints_xy = _decode_yolo11_pose_keypoints_xy(
        pred_xy=pred_keypoints_reshaped[..., :2],
        anchor_points=foreground_anchor_points,
        strides=stride_values,
    )
    gt_xy = foreground_gt_keypoints[..., :2]
    keypoint_mask = build_pose_visibility_mask(
        torch_module=torch_module,
        gt_keypoints=foreground_gt_keypoints,
        keypoint_dim=keypoint_dim,
    )
    keypoint_loss = compute_oks_keypoint_loss(
        torch_module=torch_module,
        pred_keypoints_xy=decoded_keypoints_xy,
        gt_keypoints_xy=gt_xy,
        keypoint_mask=keypoint_mask,
        area=build_pose_box_area(gt_boxes=foreground_gt_boxes),
        sigmas=build_pose_oks_sigmas(
            torch_module=torch_module,
            num_keypoints=keypoint_count,
            device=foreground_pred_keypoints.device,
            dtype=foreground_pred_keypoints.dtype,
        ),
    )
    visibility_loss = foreground_pred_keypoints.new_zeros(())
    if keypoint_dim > 2:
        visibility_loss = compute_visibility_loss(
            torch_module=torch_module,
            pred_visibility_logits=pred_keypoints_reshaped[..., 2],
            keypoint_mask=keypoint_mask,
        )
    return keypoint_loss, visibility_loss


def _decode_yolo11_pose_keypoints_xy(
    *,
    pred_xy: Any,
    anchor_points: Any,
    strides: Any,
) -> Any:
    """按 Ultralytics YOLO11 pose 训练规则解码关键点坐标。"""

    anchors_xy = anchor_points.unsqueeze(1)
    return ((pred_xy * 2.0) + anchors_xy - 0.5) * strides.unsqueeze(1)


__all__ = ["compute_yolo11_pose_loss"]
