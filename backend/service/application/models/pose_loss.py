"""Pose（关键点检测）损失计算模块。

复用 detection 的分类、框和 DFL 损失，并补齐：
- OKS 风格关键点位置损失
- 关键点可见性 BCE 损失
- Pose26 的 RLE（Residual Log-likelihood Estimation）损失
"""

from __future__ import annotations

from typing import Any


_POSE26_OKS_SIGMA = (
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
_POSE26_RLE_WEIGHT = (
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


def compute_pose_loss(
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
) -> dict[str, Any]:
    """计算 Pose 完整损失。"""

    from backend.service.application.models.yolo_primary_detection_training import (
        _assign_detection_targets,
        _bbox_xyxy_to_distances,
        _box_iou_aligned,
        _decode_detection_training_predictions,
        _distribution_focal_loss,
    )

    pose_head = model.model[-1]
    reg_max = int(pose_head.reg_max)
    nk = int(kpt_shape[0])
    kpt_dim = int(kpt_shape[1])
    is_pose26 = hasattr(pose_head, "flow_model") and pose_head.flow_model is not None

    prediction_bundle = _decode_detection_training_predictions(
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

    raw_kpts = raw_outputs.get("kpts")
    pred_kpts = (
        raw_kpts.permute(0, 2, 1).contiguous()
        if raw_kpts is not None
        else None
    )
    pred_kpts_sigma = None
    if is_pose26:
        raw_kpts_sigma = raw_outputs.get("kpts_sigma")
        if raw_kpts_sigma is not None:
            pred_kpts_sigma = raw_kpts_sigma.permute(0, 2, 1).contiguous()

    bs = int(class_logits.shape[0])
    total_class_loss = class_logits.new_zeros(())
    total_box_loss = class_logits.new_zeros(())
    total_dfl_loss = class_logits.new_zeros(())
    total_kpt_loss = class_logits.new_zeros(())
    total_visibility_loss = class_logits.new_zeros(())
    total_rle_loss = class_logits.new_zeros(()) if is_pose26 else None
    total_foreground = 0
    total_target_score = class_logits.new_zeros(())

    for bi in range(bs):
        img_class_logits = class_logits[bi]
        img_class_probs = class_probabilities[bi]
        img_pred_boxes = pred_boxes[bi]
        target_scores = torch.zeros_like(img_class_logits)

        target = batch_targets[bi]
        gt_boxes_list = getattr(target, "boxes_xyxy", None) or getattr(target, "boxes", None)
        gt_classes_list = getattr(target, "category_indexes", None) or getattr(target, "class_ids", None)
        gt_kpts = getattr(target, "keypoints", None)

        if gt_boxes_list is not None and len(gt_boxes_list) > 0:
            gt_boxes = torch.tensor(gt_boxes_list, device=img_pred_boxes.device, dtype=img_pred_boxes.dtype)
            gt_classes = torch.tensor(gt_classes_list, device=img_pred_boxes.device, dtype=torch.long)

            # 标签分配只决定正负样本和质量分数，必须与反向传播图隔离。
            # Ultralytics 的 pose loss 同样使用 detach 后的 box/score 进入 assigner。
            with torch.no_grad():
                assignment = _assign_detection_targets(
                    torch_module=torch,
                    pred_boxes=img_pred_boxes.detach(),
                    class_probabilities=img_class_probs.detach(),
                    anchor_centers_xy=anchor_centers_xy,
                    gt_boxes=gt_boxes,
                    gt_classes=gt_classes,
                    topk=assign_topk,
                    alpha=assign_alpha,
                    beta=assign_beta,
                )

            fg_mask = assignment["foreground_mask"]
            if int(fg_mask.sum().item()) > 0:
                fg_assigned = assignment["assigned_gt_indices"][fg_mask]
                quality_scores = assignment["quality_scores"][fg_mask]
                target_scores[fg_mask, gt_classes[fg_assigned]] = quality_scores

                fg_pred_boxes = img_pred_boxes[fg_mask]
                fg_gt_boxes = gt_boxes[fg_assigned]

                iou_vals = _box_iou_aligned(
                    torch_module=torch,
                    boxes1=fg_pred_boxes,
                    boxes2=fg_gt_boxes,
                ).clamp(0.0, 1.0)
                total_box_loss = total_box_loss + (1.0 - iou_vals).sum()

                fg_anchor_pts = anchor_points[fg_mask]
                fg_stride = stride_tensor[fg_mask]
                target_distances = _bbox_xyxy_to_distances(
                    torch_module=torch,
                    boxes_xyxy=fg_gt_boxes,
                    anchor_points=fg_anchor_pts,
                    stride_tensor=fg_stride,
                    reg_max=reg_max,
                )
                if reg_max > 1:
                    fg_dist_logits = distance_logits[bi][fg_mask].view(-1, 4, reg_max)
                    total_dfl_loss = total_dfl_loss + _distribution_focal_loss(
                        torch_module=torch,
                        logits=fg_dist_logits,
                        target=target_distances,
                    ).sum()
                else:
                    fg_dist_logits = distance_logits[bi][fg_mask].view(-1, 4)
                    total_dfl_loss = total_dfl_loss + torch.nn.functional.smooth_l1_loss(
                        torch.nn.functional.softplus(fg_dist_logits),
                        target_distances,
                        reduction="sum",
                    )

                if pred_kpts is not None and gt_kpts is not None and len(gt_kpts) > 0:
                    fg_pred_kpts = pred_kpts[bi][fg_mask]
                    fg_gt_kpts = _normalize_gt_keypoints_tensor(
                        torch_module=torch,
                        raw_keypoints=gt_kpts,
                        assigned_indices=fg_assigned,
                        num_keypoints=nk,
                        keypoint_dim=kpt_dim,
                        device=fg_pred_kpts.device,
                        dtype=fg_pred_kpts.dtype,
                    )
                    num_fg = int(fg_pred_kpts.shape[0])
                    pred_kpts_reshaped = fg_pred_kpts.view(num_fg, nk, kpt_dim)

                    fg_strides = fg_stride.view(-1, 1)
                    fg_anchors = fg_anchor_pts * fg_strides
                    decoded_kpts_xy = _decode_pose_keypoints_xy(
                        pred_xy=pred_kpts_reshaped[..., :2],
                        anchors_xy=fg_anchors,
                        strides=fg_strides,
                        is_pose26=is_pose26,
                    )
                    gt_xy = fg_gt_kpts[..., :2]
                    kpt_mask = _build_pose_visibility_mask(
                        torch_module=torch,
                        gt_keypoints=fg_gt_kpts,
                        keypoint_dim=kpt_dim,
                    )
                    area = _build_pose_box_area(
                        torch_module=torch,
                        gt_boxes=fg_gt_boxes,
                    )
                    sigmas = _build_pose_oks_sigmas(
                        torch_module=torch,
                        num_keypoints=nk,
                        device=fg_pred_kpts.device,
                        dtype=fg_pred_kpts.dtype,
                    )
                    total_kpt_loss = total_kpt_loss + compute_oks_keypoint_loss(
                        torch_module=torch,
                        pred_keypoints_xy=decoded_kpts_xy,
                        gt_keypoints_xy=gt_xy,
                        keypoint_mask=kpt_mask,
                        area=area,
                        sigmas=sigmas,
                    )

                    if kpt_dim > 2:
                        total_visibility_loss = total_visibility_loss + compute_visibility_loss(
                            torch_module=torch,
                            pred_visibility_logits=pred_kpts_reshaped[..., 2],
                            keypoint_mask=kpt_mask,
                        )

                    if is_pose26 and pred_kpts_sigma is not None and total_rle_loss is not None:
                        fg_pred_sigma = pred_kpts_sigma[bi][fg_mask].view(num_fg, nk, 2)
                        rle_target_weights = _build_pose_rle_weights(
                            torch_module=torch,
                            num_keypoints=nk,
                            device=fg_pred_kpts.device,
                            dtype=fg_pred_kpts.dtype,
                        )
                        total_rle_loss = total_rle_loss + compute_rle_loss(
                            torch_module=torch,
                            flow_model=pose_head.flow_model,
                            pred_keypoints_xy=decoded_kpts_xy,
                            pred_sigma_logits=fg_pred_sigma,
                            gt_keypoints_xy=gt_xy,
                            keypoint_mask=kpt_mask,
                            target_weights=rle_target_weights,
                        )

                total_foreground += int(fg_mask.sum().item())
                total_target_score = total_target_score + quality_scores.sum()

        total_class_loss = total_class_loss + torch.nn.functional.binary_cross_entropy_with_logits(
            img_class_logits,
            target_scores,
            reduction="sum",
        )

    normalizer = total_target_score.clamp_min(1.0)
    fg_norm = max(total_foreground, 1)
    class_loss = total_class_loss / normalizer
    box_loss = total_box_loss / fg_norm
    dfl_loss = total_dfl_loss / fg_norm
    kpt_loss = total_kpt_loss / fg_norm
    visibility_loss = total_visibility_loss / fg_norm

    rle_loss = None
    if is_pose26 and total_rle_loss is not None:
        rle_loss = total_rle_loss / fg_norm

    total_loss = (
        class_loss * class_loss_weight
        + box_loss * box_loss_weight
        + dfl_loss * dfl_loss_weight
        + kpt_loss * kpt_loss_weight
        + visibility_loss * visibility_loss_weight
    )
    if is_pose26 and rle_loss is not None:
        total_loss = total_loss + rle_loss * rle_loss_weight

    result = {
        "loss": total_loss,
        "class_loss": class_loss,
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
        "kpt_loss": kpt_loss,
        "visibility_loss": visibility_loss,
    }
    if is_pose26 and rle_loss is not None:
        result["rle_loss"] = rle_loss
    return result


def compute_oks_keypoint_loss(
    *,
    torch_module: Any,
    pred_keypoints_xy: Any,
    gt_keypoints_xy: Any,
    keypoint_mask: Any,
    area: Any,
    sigmas: Any,
) -> Any:
    """按 OKS 公式计算关键点位置损失。"""

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
    """计算关键点可见性 BCE 损失。"""

    return torch_module.nn.functional.binary_cross_entropy_with_logits(
        pred_visibility_logits,
        keypoint_mask.float(),
        reduction="mean",
    )


def compute_rle_loss(
    *,
    torch_module: Any,
    flow_model: Any,
    pred_keypoints_xy: Any,
    pred_sigma_logits: Any,
    gt_keypoints_xy: Any,
    keypoint_mask: Any,
    target_weights: Any,
) -> Any:
    """计算 Pose26 的 RLE 损失。"""

    if flow_model is None:
        return pred_keypoints_xy.new_zeros(())

    visible_pred_xy = pred_keypoints_xy[keypoint_mask]
    visible_gt_xy = gt_keypoints_xy[keypoint_mask]
    visible_sigma = pred_sigma_logits.sigmoid()[keypoint_mask]
    if int(visible_pred_xy.shape[0]) <= 0:
        return pred_keypoints_xy.new_zeros(())

    expanded_target_weights = target_weights.unsqueeze(0).repeat(keypoint_mask.shape[0], 1)
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
    loss = loss + torch_module.log(visible_sigma_float * 2.0 + 1e-9) + torch_module.abs(error.float())
    loss = loss * visible_target_weights.unsqueeze(1).float()
    loss = loss.sum() / max(int(loss.shape[0]), 1)
    return loss.to(dtype=pred_keypoints_xy.dtype)


def _build_pose_oks_sigmas(
    *,
    torch_module: Any,
    num_keypoints: int,
    device: Any,
    dtype: Any,
) -> Any:
    """构建当前关键点配置对应的 OKS sigma。"""

    if num_keypoints == len(_POSE26_OKS_SIGMA):
        values = _POSE26_OKS_SIGMA
    else:
        values = tuple(1.0 / max(num_keypoints, 1) for _ in range(num_keypoints))
    return torch_module.tensor(values, device=device, dtype=dtype).view(1, num_keypoints)


def _build_pose_rle_weights(
    *,
    torch_module: Any,
    num_keypoints: int,
    device: Any,
    dtype: Any,
) -> Any:
    """构建当前关键点配置对应的 RLE 权重。"""

    if num_keypoints == len(_POSE26_RLE_WEIGHT):
        values = _POSE26_RLE_WEIGHT
    else:
        values = tuple(1.0 for _ in range(num_keypoints))
    return torch_module.tensor(values, device=device, dtype=dtype)


def _decode_pose_keypoints_xy(
    *,
    pred_xy: Any,
    anchors_xy: Any,
    strides: Any,
    is_pose26: bool,
) -> Any:
    """按模型类型把关键点分支输出解码到输入图坐标。"""

    if is_pose26:
        return anchors_xy.unsqueeze(1) + pred_xy * strides.unsqueeze(1)
    return anchors_xy.unsqueeze(1) + pred_xy * strides.unsqueeze(1) * 2.0


def _build_pose_box_area(
    *,
    torch_module: Any,
    gt_boxes: Any,
) -> Any:
    """从 matched gt boxes 构建 OKS 所需面积。"""

    widths = (gt_boxes[:, 2] - gt_boxes[:, 0]).clamp_min(1.0)
    heights = (gt_boxes[:, 3] - gt_boxes[:, 1]).clamp_min(1.0)
    return (widths * heights).view(-1, 1)


def _build_pose_visibility_mask(
    *,
    torch_module: Any,
    gt_keypoints: Any,
    keypoint_dim: int,
) -> Any:
    """构建关键点可见性 mask。"""

    if keypoint_dim > 2:
        return gt_keypoints[..., 2] > 0
    return torch_module.ones(
        gt_keypoints.shape[0],
        gt_keypoints.shape[1],
        device=gt_keypoints.device,
        dtype=torch_module.bool,
    )


def _normalize_gt_keypoints_tensor(
    *,
    torch_module: Any,
    raw_keypoints: Any,
    assigned_indices: Any,
    num_keypoints: int,
    keypoint_dim: int,
    device: Any,
    dtype: Any,
) -> Any:
    """把 batch target 里的关键点规整成固定张量。"""

    target_width = num_keypoints * keypoint_dim
    num_targets = int(assigned_indices.shape[0])
    normalized = torch_module.zeros(
        (num_targets, target_width),
        device=device,
        dtype=dtype,
    )

    if isinstance(raw_keypoints, list):
        for output_index, assigned_index in enumerate(assigned_indices.tolist()):
            if assigned_index >= len(raw_keypoints):
                continue
            value = raw_keypoints[assigned_index]
            if not isinstance(value, list | tuple) or len(value) <= 0:
                continue
            limited_values = [float(item) for item in value[:target_width]]
            normalized[output_index, : len(limited_values)] = torch_module.tensor(
                limited_values,
                device=device,
                dtype=dtype,
            )
        return normalized.view(num_targets, num_keypoints, keypoint_dim)

    if isinstance(raw_keypoints, torch_module.Tensor):
        selected = raw_keypoints[assigned_indices].to(device=device, dtype=dtype)
        if selected.dim() == 3:
            return selected
        if selected.dim() == 2 and int(selected.shape[1]) == target_width:
            return selected.view(num_targets, num_keypoints, keypoint_dim)
        if selected.dim() == 1 and int(selected.shape[0]) == target_width:
            return selected.view(1, num_keypoints, keypoint_dim)

    return normalized.view(num_targets, num_keypoints, keypoint_dim)
