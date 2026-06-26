"""YOLO11 OBB loss。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.decode import (
    OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI,
    decode_obb_angle_logits,
)
from backend.service.application.models.yolo_core_common.geometry import make_anchors
from backend.service.application.models.yolo_core_common.losses.obb import (
    compute_obb_angle_loss,
    probiou_aligned,
)
from backend.service.application.models.yolo11_core.assigners import (
    assign_yolo11_obb_targets,
)
from backend.service.application.models.yolo11_core.losses.detection import (
    yolo11_distribution_focal_loss,
)
from backend.service.application.models.yolo11_core.targets import (
    yolo11_decode_distances_to_rboxes,
    yolo11_rbox_to_distances,
    yolo11_scale_rbox_to_grid,
)


def compute_yolo11_obb_loss(
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
    assign_topk2: int | None = None,
) -> dict[str, Any]:
    """计算 YOLO11 OBB 的分类、旋转框、DFL 和角度损失。"""

    obb_head = model.model[-1]
    reg_max = int(obb_head.reg_max)
    raw_boxes = raw_outputs["boxes"]
    raw_scores = raw_outputs["scores"]
    raw_angle = raw_outputs["angle"]
    feature_maps = raw_outputs["feats"]
    distances = (
        obb_head.dfl(raw_boxes)
        if reg_max > 1
        else torch.nn.functional.softplus(raw_boxes)
    )
    angle_decode_mode = getattr(
        obb_head,
        "angle_decode_mode",
        OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI,
    )
    pred_angles = _normalize_yolo11_obb_angle_tensor(
        torch_module=torch,
        pred_angles=decode_obb_angle_logits(
            angle_logits=raw_angle,
            mode=angle_decode_mode,
        ),
    )
    anchor_points, stride_tensor = make_anchors(
        feature_maps=feature_maps,
        strides=tuple(int(item) for item in obb_head.strides),
    )

    batch_size = int(raw_boxes.shape[0])
    decoded_distances = distances.permute(0, 2, 1).contiguous()
    class_logits_all = raw_scores.permute(0, 2, 1).contiguous()
    distance_logits_all = raw_boxes.permute(0, 2, 1).contiguous()
    pred_rboxes_grid = yolo11_decode_distances_to_rboxes(
        torch_module=torch,
        pred_dist=decoded_distances,
        pred_angle=pred_angles,
        anchor_points=anchor_points.unsqueeze(0).expand(batch_size, -1, -1),
    )
    pred_rboxes_pixel = pred_rboxes_grid.clone()
    pred_rboxes_pixel[..., :4] = pred_rboxes_pixel[..., :4] * stride_tensor.view(
        1, -1, 1
    )
    anchor_centers_xy = anchor_points * stride_tensor
    min_candidate_box_size = float(min(int(item) for item in obb_head.strides))

    total_class_loss = class_logits_all.new_zeros(())
    total_box_loss = class_logits_all.new_zeros(())
    total_dfl_loss = class_logits_all.new_zeros(())
    total_angle_loss = class_logits_all.new_zeros(())
    total_target_score = class_logits_all.new_zeros(())

    for batch_index in range(batch_size):
        loss_state = _compute_yolo11_obb_image_loss(
            torch_module=torch,
            image_class_logits=class_logits_all[batch_index],
            image_pred_rboxes_grid=pred_rboxes_grid[batch_index],
            image_pred_rboxes_pixel=pred_rboxes_pixel[batch_index],
            image_angle=pred_angles[batch_index],
            target=batch_targets[batch_index],
            anchor_points=anchor_points,
            stride_tensor=stride_tensor,
            anchor_centers_xy=anchor_centers_xy,
            distance_logits=distance_logits_all[batch_index],
            reg_max=reg_max,
            num_classes=num_classes,
            min_candidate_box_size=min_candidate_box_size,
            assign_topk=assign_topk,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            assign_topk2=assign_topk2,
        )
        total_class_loss = total_class_loss + loss_state["class_loss"]
        total_box_loss = total_box_loss + loss_state["box_loss"]
        total_dfl_loss = total_dfl_loss + loss_state["dfl_loss"]
        total_angle_loss = total_angle_loss + loss_state["angle_loss"]
        total_target_score = total_target_score + loss_state["target_score"]

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
    batch_size = max(1, len(batch_targets))
    return {
        "loss": total_loss * batch_size,
        "class_loss": class_loss,
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
        "angle_loss": angle_loss,
    }


def yolo11_probiou_aligned(torch_module: Any, obb1: Any, obb2: Any) -> Any:
    """计算 YOLO11 OBB 一一对应旋转框 probiou。"""

    return probiou_aligned(
        torch_module=torch_module,
        obb1=obb1,
        obb2=obb2,
    )


def _compute_yolo11_obb_image_loss(
    *,
    torch_module: Any,
    image_class_logits: Any,
    image_pred_rboxes_grid: Any,
    image_pred_rboxes_pixel: Any,
    image_angle: Any,
    target: Any,
    anchor_points: Any,
    stride_tensor: Any,
    anchor_centers_xy: Any,
    distance_logits: Any,
    reg_max: int,
    num_classes: int,
    min_candidate_box_size: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    assign_topk2: int | None,
) -> dict[str, Any]:
    """计算单张图片的 YOLO11 OBB 训练损失。"""

    _ = num_classes
    target_scores = torch_module.zeros_like(image_class_logits)
    zero_loss = image_class_logits.new_zeros(())
    gt_rboxes_list = getattr(target, "boxes_xywhr", None)
    gt_classes_list = getattr(target, "category_indexes", None)
    if gt_rboxes_list is None or len(gt_rboxes_list) == 0:
        return {
            "class_loss": torch_module.nn.functional.binary_cross_entropy_with_logits(
                image_class_logits,
                target_scores,
                reduction="sum",
            ),
            "box_loss": zero_loss,
            "dfl_loss": zero_loss,
            "angle_loss": zero_loss,
            "target_score": zero_loss,
        }

    gt_rboxes = torch_module.tensor(
        gt_rboxes_list,
        device=image_pred_rboxes_grid.device,
        dtype=image_pred_rboxes_grid.dtype,
    )
    gt_classes = torch_module.tensor(
        gt_classes_list,
        device=image_pred_rboxes_grid.device,
        dtype=torch_module.long,
    )
    with torch_module.no_grad():
        assignment = assign_yolo11_obb_targets(
            torch_module=torch_module,
            pred_rboxes=image_pred_rboxes_pixel.detach(),
            class_probabilities=image_class_logits.detach().sigmoid(),
            anchor_centers_xy=anchor_centers_xy,
            gt_rboxes=gt_rboxes,
            gt_classes=gt_classes,
            topk=assign_topk,
            alpha=assign_alpha,
            beta=assign_beta,
            min_candidate_box_size=min_candidate_box_size,
            topk2=assign_topk2,
        )

    foreground_mask = assignment["foreground_mask"]
    if int(foreground_mask.sum().item()) <= 0:
        return {
            "class_loss": torch_module.nn.functional.binary_cross_entropy_with_logits(
                image_class_logits,
                target_scores,
                reduction="sum",
            ),
            "box_loss": zero_loss,
            "dfl_loss": zero_loss,
            "angle_loss": zero_loss,
            "target_score": zero_loss,
        }

    assigned_indices = assignment["assigned_gt_indices"][foreground_mask]
    quality_scores = assignment["quality_scores"][foreground_mask]
    target_scores[foreground_mask, gt_classes[assigned_indices]] = quality_scores
    foreground_pred_rboxes_grid = image_pred_rboxes_grid[foreground_mask]
    foreground_gt_rboxes_pixel = gt_rboxes[assigned_indices]
    foreground_stride = stride_tensor[foreground_mask]
    foreground_gt_rboxes_grid = yolo11_scale_rbox_to_grid(
        rboxes=foreground_gt_rboxes_pixel,
        stride_tensor=foreground_stride,
    )
    iou_values = yolo11_probiou_aligned(
        torch_module=torch_module,
        obb1=foreground_pred_rboxes_grid,
        obb2=foreground_gt_rboxes_grid,
    ).clamp(0.0, 1.0)
    box_loss = ((1.0 - iou_values) * quality_scores).sum()
    dfl_loss = _compute_yolo11_obb_dfl_loss(
        torch_module=torch_module,
        distance_logits=distance_logits,
        foreground_mask=foreground_mask,
        foreground_gt_rboxes_pixel=foreground_gt_rboxes_pixel,
        foreground_anchor_points=anchor_points[foreground_mask],
        foreground_stride=foreground_stride,
        quality_scores=quality_scores,
        reg_max=reg_max,
    )
    angle_loss = compute_obb_angle_loss(
        torch_module=torch_module,
        pred_angle=image_angle[foreground_mask].view(-1, 1),
        gt_angle=foreground_gt_rboxes_pixel[:, 4:5],
        gt_wh=foreground_gt_rboxes_pixel[:, 2:4],
        target_scores=quality_scores,
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
        "angle_loss": angle_loss * quality_scores.sum(),
        "target_score": quality_scores.sum(),
    }


def _compute_yolo11_obb_dfl_loss(
    *,
    torch_module: Any,
    distance_logits: Any,
    foreground_mask: Any,
    foreground_gt_rboxes_pixel: Any,
    foreground_anchor_points: Any,
    foreground_stride: Any,
    quality_scores: Any,
    reg_max: int,
) -> Any:
    """计算 YOLO11 OBB DFL 分量。"""

    target_distances = yolo11_rbox_to_distances(
        torch_module=torch_module,
        rboxes=foreground_gt_rboxes_pixel,
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


def _normalize_yolo11_obb_angle_tensor(
    *,
    torch_module: Any,
    pred_angles: Any,
) -> Any:
    """把 YOLO11 OBB angle 输出规整为 (bs, anchors, 1)。"""

    _ = torch_module
    if pred_angles.dim() == 3 and int(pred_angles.shape[1]) == 1:
        return pred_angles.transpose(1, 2).contiguous()
    if pred_angles.dim() == 3 and int(pred_angles.shape[2]) == 1:
        return pred_angles.contiguous()
    if pred_angles.dim() == 2:
        return pred_angles.unsqueeze(-1).contiguous()
    raise ValueError(f"YOLO11 OBB angle 输出 shape 不合法: {tuple(pred_angles.shape)}")


__all__ = [
    "compute_yolo11_obb_loss",
    "yolo11_probiou_aligned",
]
