"""YOLOv8 pose loss。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolov8_core.assigners import (
    assign_yolov8_pose_targets,
    yolov8_pose_box_iou_aligned,
)
from backend.service.application.models.yolov8_core.decode import (
    decode_yolov8_detection_training_predictions,
    decode_yolov8_pose_keypoints_xy,
)
from backend.service.application.models.yolov8_core.losses.detection import (
    yolov8_distribution_focal_loss,
)
from backend.service.application.models.yolov8_core.targets import (
    normalize_yolov8_gt_keypoints_tensor,
    yolov8_bbox_xyxy_to_distances,
)

COCO_KEYPOINT_OKS_SIGMA = (
    0.026,
    0.025,
    0.025,
    0.035,
    0.035,
    0.079,
    0.079,
    0.072,
    0.072,
    0.062,
    0.062,
    0.107,
    0.107,
    0.087,
    0.087,
    0.089,
    0.089,
)


def compute_yolov8_pose_loss(
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
) -> dict[str, Any]:
    """计算 YOLOv8 pose 损失。"""

    pose_head = model.model[-1]
    reg_max = int(pose_head.reg_max)
    keypoint_count = int(kpt_shape[0])
    keypoint_dim = int(kpt_shape[1])

    prediction_bundle = decode_yolov8_detection_training_predictions(
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
        image_class_logits = class_logits[batch_index]
        image_class_probabilities = class_probabilities[batch_index]
        image_pred_boxes = pred_boxes[batch_index]
        target_scores = torch.zeros_like(image_class_logits)

        target = batch_targets[batch_index]
        gt_boxes_list = getattr(target, "boxes_xyxy", None) or getattr(target, "boxes", None)
        gt_classes_list = getattr(target, "category_indexes", None) or getattr(
            target,
            "class_ids",
            None,
        )
        gt_keypoints = getattr(target, "keypoints", None)

        if gt_boxes_list is not None and len(gt_boxes_list) > 0:
            gt_boxes = torch.tensor(
                gt_boxes_list,
                device=image_pred_boxes.device,
                dtype=image_pred_boxes.dtype,
            )
            gt_classes = torch.tensor(
                gt_classes_list,
                device=image_pred_boxes.device,
                dtype=torch.long,
            )

            with torch.no_grad():
                assignment = assign_yolov8_pose_targets(
                    torch_module=torch,
                    pred_boxes=image_pred_boxes.detach(),
                    class_probabilities=image_class_probabilities.detach(),
                    anchor_centers_xy=anchor_centers_xy,
                    gt_boxes=gt_boxes,
                    gt_classes=gt_classes,
                    topk=assign_topk,
                    alpha=assign_alpha,
                    beta=assign_beta,
                )

            foreground_mask = assignment["foreground_mask"]
            if int(foreground_mask.sum().item()) > 0:
                assigned_indices = assignment["assigned_gt_indices"][foreground_mask]
                quality_scores = assignment["quality_scores"][foreground_mask]
                target_scores[foreground_mask, gt_classes[assigned_indices]] = quality_scores

                foreground_pred_boxes = image_pred_boxes[foreground_mask]
                foreground_gt_boxes = gt_boxes[assigned_indices]
                iou_values = yolov8_pose_box_iou_aligned(
                    torch_module=torch,
                    boxes1=foreground_pred_boxes,
                    boxes2=foreground_gt_boxes,
                ).clamp(0.0, 1.0)
                total_box_loss = total_box_loss + ((1.0 - iou_values) * quality_scores).sum()

                foreground_anchor_points = anchor_points[foreground_mask]
                foreground_stride = stride_tensor[foreground_mask]
                target_distances = yolov8_bbox_xyxy_to_distances(
                    torch_module=torch,
                    boxes_xyxy=foreground_gt_boxes,
                    anchor_points=foreground_anchor_points,
                    stride_tensor=foreground_stride,
                    reg_max=reg_max,
                )
                if reg_max > 1:
                    foreground_distance_logits = distance_logits[batch_index][
                        foreground_mask
                    ].view(-1, 4, reg_max)
                    image_dfl_loss = yolov8_distribution_focal_loss(
                        torch_module=torch,
                        logits=foreground_distance_logits,
                        target=target_distances,
                    )
                    total_dfl_loss = total_dfl_loss + (image_dfl_loss * quality_scores).sum()
                else:
                    foreground_distance_logits = distance_logits[batch_index][
                        foreground_mask
                    ].view(-1, 4)
                    image_dfl_loss = torch.nn.functional.smooth_l1_loss(
                        torch.nn.functional.softplus(foreground_distance_logits),
                        target_distances,
                        reduction="none",
                    )
                    total_dfl_loss = total_dfl_loss + (
                        image_dfl_loss.mean(dim=1) * quality_scores
                    ).sum()

                if (
                    pred_keypoints is not None
                    and gt_keypoints is not None
                    and len(gt_keypoints) > 0
                ):
                    total_keypoint_loss, total_visibility_loss = _accumulate_yolov8_pose_keypoint_loss(
                        torch_module=torch,
                        pred_keypoints=pred_keypoints,
                        batch_index=batch_index,
                        foreground_mask=foreground_mask,
                        assigned_indices=assigned_indices,
                        gt_keypoints=gt_keypoints,
                        keypoint_count=keypoint_count,
                        keypoint_dim=keypoint_dim,
                        foreground_anchor_points=foreground_anchor_points,
                        foreground_stride=foreground_stride,
                        foreground_gt_boxes=foreground_gt_boxes,
                        total_keypoint_loss=total_keypoint_loss,
                        total_visibility_loss=total_visibility_loss,
                    )

                total_foreground += int(foreground_mask.sum().item())
                total_target_score = total_target_score + quality_scores.sum()

        total_class_loss = total_class_loss + torch.nn.functional.binary_cross_entropy_with_logits(
            image_class_logits,
            target_scores,
            reduction="sum",
        )

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


def _accumulate_yolov8_pose_keypoint_loss(
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
    total_keypoint_loss: Any,
    total_visibility_loss: Any,
) -> tuple[Any, Any]:
    """累加 YOLOv8 pose 关键点位置和可见性损失。"""

    foreground_pred_keypoints = pred_keypoints[batch_index][foreground_mask]
    foreground_gt_keypoints = normalize_yolov8_gt_keypoints_tensor(
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
    foreground_stride_values = foreground_stride.view(-1, 1)
    foreground_anchors = foreground_anchor_points * foreground_stride_values
    decoded_keypoints_xy = decode_yolov8_pose_keypoints_xy(
        pred_xy=pred_keypoints_reshaped[..., :2],
        anchors_xy=foreground_anchors,
        strides=foreground_stride_values,
    )
    gt_xy = foreground_gt_keypoints[..., :2]
    keypoint_mask = build_pose_visibility_mask(
        torch_module=torch_module,
        gt_keypoints=foreground_gt_keypoints,
        keypoint_dim=keypoint_dim,
    )
    area = build_pose_box_area(gt_boxes=foreground_gt_boxes)
    sigmas = build_pose_oks_sigmas(
        torch_module=torch_module,
        num_keypoints=keypoint_count,
        device=foreground_pred_keypoints.device,
        dtype=foreground_pred_keypoints.dtype,
    )
    keypoint_loss = compute_oks_keypoint_loss(
        torch_module=torch_module,
        pred_keypoints_xy=decoded_keypoints_xy,
        gt_keypoints_xy=gt_xy,
        keypoint_mask=keypoint_mask,
        area=area,
        sigmas=sigmas,
    )
    total_keypoint_loss = total_keypoint_loss + keypoint_loss * foreground_count
    if keypoint_dim > 2:
        visibility_loss = compute_visibility_loss(
            torch_module=torch_module,
            pred_visibility_logits=pred_keypoints_reshaped[..., 2],
            keypoint_mask=keypoint_mask,
        )
        total_visibility_loss = total_visibility_loss + visibility_loss * foreground_count
    return total_keypoint_loss, total_visibility_loss


def yolov8_pose_box_area(*, gt_boxes: Any) -> Any:
    """从 matched gt boxes 构建 YOLOv8 OKS 所需面积。"""

    widths = (gt_boxes[:, 2] - gt_boxes[:, 0]).clamp_min(1.0)
    heights = (gt_boxes[:, 3] - gt_boxes[:, 1]).clamp_min(1.0)
    return (widths * heights).view(-1, 1)


def build_pose_box_area(*, gt_boxes: Any) -> Any:
    """兼容当前文件内调用的 YOLOv8 pose 面积构建入口。"""

    return yolov8_pose_box_area(gt_boxes=gt_boxes)


def build_pose_oks_sigmas(
    *,
    torch_module: Any,
    num_keypoints: int,
    device: Any,
    dtype: Any,
) -> Any:
    """构建 YOLOv8 pose OKS sigma。"""

    if num_keypoints == len(COCO_KEYPOINT_OKS_SIGMA):
        values = COCO_KEYPOINT_OKS_SIGMA
    else:
        values = tuple(1.0 / max(num_keypoints, 1) for _ in range(num_keypoints))
    return torch_module.tensor(values, device=device, dtype=dtype).view(1, num_keypoints)


def build_pose_visibility_mask(
    *,
    torch_module: Any,
    gt_keypoints: Any,
    keypoint_dim: int,
) -> Any:
    """构建 YOLOv8 pose 关键点可见性 mask。"""

    if keypoint_dim > 2:
        return gt_keypoints[..., 2] > 0
    return torch_module.ones(
        gt_keypoints.shape[0],
        gt_keypoints.shape[1],
        device=gt_keypoints.device,
        dtype=torch_module.bool,
    )


def compute_oks_keypoint_loss(
    *,
    torch_module: Any,
    pred_keypoints_xy: Any,
    gt_keypoints_xy: Any,
    keypoint_mask: Any,
    area: Any,
    sigmas: Any,
) -> Any:
    """按 YOLOv8 pose OKS 公式计算关键点位置损失。"""

    distance_sq = (
        (pred_keypoints_xy[..., 0] - gt_keypoints_xy[..., 0]).pow(2)
        + (pred_keypoints_xy[..., 1] - gt_keypoints_xy[..., 1]).pow(2)
    )
    keypoint_mask_float = keypoint_mask.float()
    visible_count = torch_module.sum(keypoint_mask_float, dim=1) + 1e-9
    keypoint_loss_factor = keypoint_mask.shape[1] / visible_count
    oks_denominator = ((2 * sigmas).pow(2) * (area + 1e-9) * 2).clamp_min(1e-9)
    error = distance_sq / oks_denominator
    return (
        keypoint_loss_factor.view(-1, 1)
        * ((1 - torch_module.exp(-error)) * keypoint_mask_float)
    ).mean()


def compute_visibility_loss(
    *,
    torch_module: Any,
    pred_visibility_logits: Any,
    keypoint_mask: Any,
) -> Any:
    """计算 YOLOv8 pose 关键点可见性 BCE 损失。"""

    return torch_module.nn.functional.binary_cross_entropy_with_logits(
        pred_visibility_logits,
        keypoint_mask.float(),
        reduction="mean",
    )

__all__ = ["compute_yolov8_pose_loss"]
