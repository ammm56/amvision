"""YOLO26 pose loss。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo26_core.assigners import (
    assign_yolo26_pose_targets,
    yolo26_pose_box_iou_aligned,
)
from backend.service.application.models.yolo26_core.decode import (
    decode_yolo26_detection_training_predictions,
)
from backend.service.application.models.yolo26_core.losses.detection import (
    yolo26_distribution_focal_loss,
)
from backend.service.application.models.yolo26_core.targets import (
    normalize_yolo26_gt_keypoints_tensor,
    yolo26_bbox_xyxy_to_distances,
)
from backend.service.application.models.yolo_core_common.losses.pose import (
    build_pose_box_area,
    build_pose_oks_sigmas,
    build_pose_visibility_mask,
    compute_oks_keypoint_loss,
    compute_visibility_loss,
)


YOLO26_RLE_WEIGHT = (
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.2,
    1.2,
    1.5,
    1.5,
    1.0,
    1.0,
    1.2,
    1.2,
    1.5,
    1.5,
)


def compute_yolo26_pose_loss(
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
    rle_loss_weight: float = 1.0,
    assign_topk: int = 10,
    assign_alpha: float = 0.5,
    assign_beta: float = 6.0,
    assign_topk2: int | None = None,
) -> dict[str, Any]:
    """计算 YOLO26 pose 的 box、class、DFL、keypoint 和可见性损失。"""

    _ = num_classes
    pose_head = model.model[-1]
    keypoint_count = int(kpt_shape[0])
    keypoint_dim = int(kpt_shape[1])

    prediction_bundle = decode_yolo26_detection_training_predictions(
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
    raw_keypoint_sigmas = raw_outputs.get("kpts_sigma")
    pred_keypoint_sigmas = (
        raw_keypoint_sigmas.permute(0, 2, 1).contiguous()
        if raw_keypoint_sigmas is not None
        else None
    )

    batch_size = int(class_logits.shape[0])
    total_class_loss = class_logits.new_zeros(())
    total_box_loss = class_logits.new_zeros(())
    total_dfl_loss = class_logits.new_zeros(())
    total_keypoint_loss = class_logits.new_zeros(())
    total_visibility_loss = class_logits.new_zeros(())
    total_rle_loss = class_logits.new_zeros(())
    total_foreground = 0
    total_target_score = class_logits.new_zeros(())

    for batch_index in range(batch_size):
        loss_state = _compute_yolo26_pose_image_loss(
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
            pred_keypoint_sigmas=pred_keypoint_sigmas,
            flow_model=getattr(pose_head, "flow_model", None),
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
        total_rle_loss = total_rle_loss + loss_state["rle_loss"]
        total_target_score = total_target_score + loss_state["target_score"]
        total_foreground += int(loss_state["foreground_count"])

    normalizer = total_target_score.clamp_min(1.0)
    foreground_normalizer = max(total_foreground, 1)
    class_loss = total_class_loss / normalizer
    box_loss = total_box_loss / normalizer
    dfl_loss = total_dfl_loss / normalizer
    keypoint_loss = total_keypoint_loss / foreground_normalizer
    visibility_loss = total_visibility_loss / foreground_normalizer
    rle_loss = total_rle_loss / foreground_normalizer
    total_loss = (
        class_loss * class_loss_weight
        + box_loss * box_loss_weight
        + dfl_loss * dfl_loss_weight
        + keypoint_loss * kpt_loss_weight
        + visibility_loss * visibility_loss_weight
        + rle_loss * rle_loss_weight
    )
    return {
        "loss": total_loss,
        "class_loss": class_loss,
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
        "kpt_loss": keypoint_loss,
        "visibility_loss": visibility_loss,
        "rle_loss": rle_loss,
    }


def _compute_yolo26_pose_image_loss(
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
    pred_keypoint_sigmas: Any | None,
    flow_model: Any | None,
    keypoint_count: int,
    keypoint_dim: int,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    assign_topk2: int | None,
) -> dict[str, Any]:
    """计算单张图片的 YOLO26 pose 训练损失。"""

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
            "rle_loss": zero_loss,
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
        assignment = assign_yolo26_pose_targets(
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
            "rle_loss": zero_loss,
            "foreground_count": 0,
            "target_score": zero_loss,
        }

    assigned_indices = assignment["assigned_gt_indices"][foreground_mask]
    quality_scores = assignment["quality_scores"][foreground_mask]
    target_scores[foreground_mask, gt_classes[assigned_indices]] = quality_scores
    foreground_pred_boxes = image_pred_boxes[foreground_mask]
    foreground_gt_boxes = gt_boxes[assigned_indices]
    iou_values = yolo26_pose_box_iou_aligned(
        torch_module=torch_module,
        boxes1=foreground_pred_boxes,
        boxes2=foreground_gt_boxes,
    ).clamp(0.0, 1.0)
    box_loss = ((1.0 - iou_values) * quality_scores).sum()
    dfl_loss = _compute_yolo26_pose_dfl_loss(
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
    rle_loss = zero_loss
    if (
        pred_keypoints is not None
        and gt_keypoints is not None
        and len(gt_keypoints) > 0
    ):
        keypoint_loss, visibility_loss, rle_loss = _compute_yolo26_pose_keypoint_losses(
            torch_module=torch_module,
            pred_keypoints=pred_keypoints,
            pred_keypoint_sigmas=pred_keypoint_sigmas,
            batch_index=batch_index,
            foreground_mask=foreground_mask,
            assigned_indices=assigned_indices,
            gt_keypoints=gt_keypoints,
            keypoint_count=keypoint_count,
            keypoint_dim=keypoint_dim,
            foreground_anchor_points=anchor_points[foreground_mask],
            foreground_stride=stride_tensor[foreground_mask],
            foreground_gt_boxes=foreground_gt_boxes,
            flow_model=flow_model,
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
        "rle_loss": rle_loss * foreground_count,
        "foreground_count": foreground_count,
        "target_score": quality_scores.sum(),
    }


def _compute_yolo26_pose_dfl_loss(
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
    """计算 YOLO26 pose DFL 分量。"""

    target_distances = yolo26_bbox_xyxy_to_distances(
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
        dfl_loss = yolo26_distribution_focal_loss(
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


def _compute_yolo26_pose_keypoint_losses(
    *,
    torch_module: Any,
    pred_keypoints: Any,
    pred_keypoint_sigmas: Any | None,
    batch_index: int,
    foreground_mask: Any,
    assigned_indices: Any,
    gt_keypoints: Any,
    keypoint_count: int,
    keypoint_dim: int,
    foreground_anchor_points: Any,
    foreground_stride: Any,
    foreground_gt_boxes: Any,
    flow_model: Any | None,
) -> tuple[Any, Any, Any]:
    """计算 YOLO26 pose 关键点位置、可见性和 RLE 损失。"""

    foreground_pred_keypoints = pred_keypoints[batch_index][foreground_mask]
    foreground_gt_keypoints = normalize_yolo26_gt_keypoints_tensor(
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
    decoded_keypoints_xy = _decode_yolo26_pose_keypoints_xy(
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
    rle_loss = foreground_pred_keypoints.new_zeros(())
    if pred_keypoint_sigmas is not None and flow_model is not None:
        foreground_pred_sigmas = pred_keypoint_sigmas[batch_index][
            foreground_mask
        ].view(foreground_count, keypoint_count, 2)
        rle_loss = compute_yolo26_rle_loss(
            torch_module=torch_module,
            flow_model=flow_model,
            pred_keypoints_xy=decoded_keypoints_xy,
            pred_sigma_logits=foreground_pred_sigmas,
            gt_keypoints_xy=gt_xy,
            keypoint_mask=keypoint_mask,
            target_weights=build_yolo26_pose_rle_weights(
                torch_module=torch_module,
                num_keypoints=keypoint_count,
                device=foreground_pred_keypoints.device,
                dtype=foreground_pred_keypoints.dtype,
            ),
        )
    return keypoint_loss, visibility_loss, rle_loss


def _decode_yolo26_pose_keypoints_xy(
    *,
    pred_xy: Any,
    anchor_points: Any,
    strides: Any,
) -> Any:
    """按 Ultralytics YOLO26 pose 训练规则解码关键点坐标。"""

    anchors_xy = anchor_points.unsqueeze(1)
    return ((pred_xy * 2.0) + anchors_xy - 0.5) * strides.unsqueeze(1)


def compute_yolo26_rle_loss(
    *,
    torch_module: Any,
    flow_model: Any,
    pred_keypoints_xy: Any,
    pred_sigma_logits: Any,
    gt_keypoints_xy: Any,
    keypoint_mask: Any,
    target_weights: Any,
) -> Any:
    """计算 YOLO26 pose 的 RLE 损失。"""

    if flow_model is None:
        return pred_keypoints_xy.new_zeros(())

    visible_pred_xy = pred_keypoints_xy[keypoint_mask]
    visible_gt_xy = gt_keypoints_xy[keypoint_mask]
    visible_sigma = pred_sigma_logits.sigmoid()[keypoint_mask]
    if int(visible_pred_xy.shape[0]) <= 0:
        return pred_keypoints_xy.new_zeros(())

    expanded_target_weights = target_weights.unsqueeze(0).repeat(
        keypoint_mask.shape[0], 1
    )
    visible_target_weights = expanded_target_weights[keypoint_mask]

    error = (visible_pred_xy - visible_gt_xy) / (visible_sigma + 1e-9)
    valid_mask = ~(torch_module.isnan(error) | torch_module.isinf(error)).any(dim=-1)
    if not bool(valid_mask.any()):
        return pred_keypoints_xy.new_zeros(())

    error = error[valid_mask].clamp(-100.0, 100.0)
    visible_sigma = visible_sigma[valid_mask]
    visible_target_weights = visible_target_weights[valid_mask]

    log_phi = flow_model.log_prob(error.float())
    visible_sigma_float = visible_sigma.float()
    loss = torch_module.log(visible_sigma_float + 1e-9) - log_phi.unsqueeze(1)
    loss = (
        loss
        + torch_module.log(visible_sigma_float * 2.0 + 1e-9)
        + torch_module.abs(error.float())
    )
    loss = loss * visible_target_weights.unsqueeze(1).float()
    loss = loss.sum() / max(int(loss.shape[0]), 1)
    return loss.to(dtype=pred_keypoints_xy.dtype)


def build_yolo26_pose_rle_weights(
    *,
    torch_module: Any,
    num_keypoints: int,
    device: Any,
    dtype: Any,
) -> Any:
    """构建 YOLO26 pose RLE 权重。"""

    if num_keypoints == len(YOLO26_RLE_WEIGHT):
        values = YOLO26_RLE_WEIGHT
    else:
        values = tuple(1.0 for _ in range(num_keypoints))
    return torch_module.tensor(values, device=device, dtype=dtype)


__all__ = [
    "build_yolo26_pose_rle_weights",
    "compute_yolo26_pose_loss",
    "compute_yolo26_rle_loss",
]
