"""YOLOv8 OBB loss。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common import make_anchors
from backend.service.application.models.yolo_core_common.losses import (
    compute_obb_angle_loss,
    distribution_focal_loss,
    probiou_aligned,
)
from backend.service.application.models.yolov8_core.assigners import (
    assign_yolov8_obb_targets,
)
from backend.service.application.models.yolov8_core.decode import (
    decode_yolov8_obb_angle_logits,
)
from backend.service.application.models.yolov8_core.targets import (
    yolov8_decode_distances_to_rboxes,
    yolov8_rbox_to_distances,
)


def compute_yolov8_obb_loss(
    *,
    torch: Any,
    model: Any,
    raw_outputs: dict[str, Any],
    batch_targets: tuple[Any, ...],
    num_classes: int,
    class_loss_weight: float = 0.5,
    box_loss_weight: float = 7.5,
    dfl_loss_weight: float = 1.5,
    angle_loss_weight: float = 0.5,
    assign_topk: int = 10,
    assign_alpha: float = 0.5,
    assign_beta: float = 6.0,
) -> dict[str, Any]:
    """计算 YOLOv8 OBB 损失。"""

    obb_head = model.model[-1]
    reg_max = int(obb_head.reg_max)

    raw_boxes = raw_outputs["boxes"]
    raw_scores = raw_outputs["scores"]
    raw_angle = raw_outputs["angle"]
    feature_maps = raw_outputs["feats"]

    distances = obb_head.dfl(raw_boxes) if reg_max > 1 else torch.nn.functional.softplus(raw_boxes)
    pred_angles = decode_yolov8_obb_angle_logits(angle_logits=raw_angle)
    anchor_points, stride_tensor = make_anchors(
        feature_maps=feature_maps,
        strides=tuple(int(item) for item in obb_head.strides),
    )

    batch_size = int(raw_boxes.shape[0])
    decoded_distances = distances.permute(0, 2, 1).contiguous()
    class_logits_all = raw_scores.permute(0, 2, 1).contiguous()
    distance_logits_all = raw_boxes.permute(0, 2, 1).contiguous()
    angle_all = _normalize_yolov8_obb_angle_tensor(
        torch_module=torch,
        pred_angles=pred_angles,
    )
    anchor_points_batch = anchor_points.unsqueeze(0).expand(batch_size, -1, -1)
    pred_rboxes = yolov8_decode_distances_to_rboxes(
        torch_module=torch,
        pred_dist=decoded_distances,
        pred_angle=angle_all,
        anchor_points=anchor_points_batch,
    )
    anchor_centers_xy = anchor_points * stride_tensor
    min_candidate_box_size = float(min(int(item) for item in obb_head.strides))

    total_class_loss = class_logits_all.new_zeros(())
    total_box_loss = class_logits_all.new_zeros(())
    total_dfl_loss = class_logits_all.new_zeros(())
    total_angle_loss = class_logits_all.new_zeros(())
    total_target_score = class_logits_all.new_zeros(())

    for batch_index in range(batch_size):
        image_class_logits = class_logits_all[batch_index]
        image_class_probabilities = image_class_logits.sigmoid()
        image_pred_rboxes = pred_rboxes[batch_index]
        image_angle = angle_all[batch_index] if angle_all.dim() == 3 else angle_all
        target_scores = torch.zeros_like(image_class_logits)

        target = batch_targets[batch_index]
        gt_rboxes_list = getattr(target, "boxes_xywhr", None)
        gt_classes_list = getattr(target, "category_indexes", None)

        if gt_rboxes_list is not None and len(gt_rboxes_list) > 0:
            gt_rboxes = torch.tensor(
                gt_rboxes_list,
                device=image_pred_rboxes.device,
                dtype=image_pred_rboxes.dtype,
            )
            gt_classes = torch.tensor(
                gt_classes_list,
                device=image_pred_rboxes.device,
                dtype=torch.long,
            )

            with torch.no_grad():
                assignment = assign_yolov8_obb_targets(
                    torch_module=torch,
                    pred_rboxes=image_pred_rboxes.detach(),
                    class_probabilities=image_class_probabilities.detach(),
                    anchor_centers_xy=anchor_centers_xy,
                    gt_rboxes=gt_rboxes,
                    gt_classes=gt_classes,
                    topk=assign_topk,
                    alpha=assign_alpha,
                    beta=assign_beta,
                    min_candidate_box_size=min_candidate_box_size,
                )

            foreground_mask = assignment["foreground_mask"]
            if bool(foreground_mask.any()):
                assigned_indices = assignment["assigned_gt_indices"][foreground_mask]
                quality_scores = assignment["quality_scores"][foreground_mask]
                foreground_pred_rboxes = image_pred_rboxes[foreground_mask]
                foreground_gt_rboxes = gt_rboxes[assigned_indices]

                iou_values = probiou_aligned(
                    torch_module=torch,
                    obb1=foreground_pred_rboxes,
                    obb2=foreground_gt_rboxes,
                ).clamp(0.0, 1.0)
                total_box_loss = total_box_loss + ((1.0 - iou_values) * quality_scores).sum()

                foreground_anchor_points = anchor_points[foreground_mask]
                foreground_stride = stride_tensor[foreground_mask]
                target_distances = yolov8_rbox_to_distances(
                    torch_module=torch,
                    rboxes=foreground_gt_rboxes,
                    anchor_points=foreground_anchor_points,
                    stride_tensor=foreground_stride,
                    reg_max=reg_max,
                )
                if reg_max > 1:
                    foreground_distance_logits = distance_logits_all[batch_index][
                        foreground_mask
                    ].view(-1, 4, reg_max)
                    image_dfl_loss = distribution_focal_loss(
                        torch_module=torch,
                        logits=foreground_distance_logits,
                        target=target_distances,
                    )
                    total_dfl_loss = total_dfl_loss + (image_dfl_loss * quality_scores).sum()
                else:
                    foreground_distance_logits = distance_logits_all[batch_index][
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

                foreground_pred_angle = image_angle[foreground_mask].view(-1, 1)
                foreground_gt_angle = foreground_gt_rboxes[:, 4:5]
                foreground_gt_wh = foreground_gt_rboxes[:, 2:4]
                image_angle_loss = compute_obb_angle_loss(
                    torch_module=torch,
                    pred_angle=foreground_pred_angle,
                    gt_angle=foreground_gt_angle,
                    gt_wh=foreground_gt_wh,
                    target_scores=quality_scores,
                )
                total_angle_loss = total_angle_loss + image_angle_loss * quality_scores.sum()
                total_target_score = total_target_score + quality_scores.sum()
                target_scores[foreground_mask, gt_classes[assigned_indices]] = quality_scores

        total_class_loss = total_class_loss + torch.nn.functional.binary_cross_entropy_with_logits(
            image_class_logits,
            target_scores,
            reduction="sum",
        )

    normalizer = total_target_score.clamp_min(1.0)
    class_loss = total_class_loss / normalizer
    box_loss = total_box_loss / normalizer
    dfl_loss = total_dfl_loss / normalizer
    angle_loss = total_angle_loss / normalizer
    total_loss = (
        class_loss * class_loss_weight
        + box_loss * box_loss_weight
        + dfl_loss * dfl_loss_weight
        + angle_loss * angle_loss_weight
    )
    return {
        "loss": total_loss,
        "class_loss": class_loss,
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
        "angle_loss": angle_loss,
    }


def _normalize_yolov8_obb_angle_tensor(
    *,
    torch_module: Any,
    pred_angles: Any,
) -> Any:
    """把 YOLOv8 OBB angle 输出规整为 (bs, anchors, 1)。"""

    if pred_angles.dim() == 3 and int(pred_angles.shape[1]) == 1:
        return pred_angles.transpose(1, 2).contiguous()
    if pred_angles.dim() == 3 and int(pred_angles.shape[2]) == 1:
        return pred_angles.contiguous()
    if pred_angles.dim() == 2:
        return pred_angles.unsqueeze(-1).contiguous()
    raise ValueError(f"YOLOv8 OBB angle 输出 shape 不合法: {tuple(pred_angles.shape)}")


__all__ = ["compute_yolov8_obb_loss"]
