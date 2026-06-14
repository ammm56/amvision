"""Pose（关键点检测）损失计算模块。

复用 detection 的分类、框和 DFL 损失，并补齐：
- OKS 风格关键点位置损失
- 关键点可见性 BCE 损失
- Pose26 的 RLE（Residual Log-likelihood Estimation）损失
"""

from __future__ import annotations

from typing import Any


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

    from backend.service.application.models.yolo_core_common.assigners import (
        assign_detection_targets,
        box_iou_aligned,
    )
    from backend.service.application.models.yolo_core_common.decode import (
        decode_detection_training_predictions,
    )
    from backend.service.application.models.yolo_core_common.losses import (
        build_pose_box_area,
        build_pose_oks_sigmas,
        build_pose_rle_weights,
        build_pose_visibility_mask,
        compute_oks_keypoint_loss,
        compute_rle_loss,
        compute_visibility_loss,
        decode_pose_keypoints_xy,
        distribution_focal_loss,
    )
    from backend.service.application.models.yolo_core_common.targets import (
        bbox_xyxy_to_distances,
        normalize_gt_keypoints_tensor,
    )

    pose_head = model.model[-1]
    reg_max = int(pose_head.reg_max)
    nk = int(kpt_shape[0])
    kpt_dim = int(kpt_shape[1])
    is_pose26 = hasattr(pose_head, "flow_model") and pose_head.flow_model is not None

    prediction_bundle = decode_detection_training_predictions(
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
                assignment = assign_detection_targets(
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

                iou_vals = box_iou_aligned(
                    torch_module=torch,
                    boxes1=fg_pred_boxes,
                    boxes2=fg_gt_boxes,
                ).clamp(0.0, 1.0)
                total_box_loss = total_box_loss + (1.0 - iou_vals).sum()

                fg_anchor_pts = anchor_points[fg_mask]
                fg_stride = stride_tensor[fg_mask]
                target_distances = bbox_xyxy_to_distances(
                    torch_module=torch,
                    boxes_xyxy=fg_gt_boxes,
                    anchor_points=fg_anchor_pts,
                    stride_tensor=fg_stride,
                    reg_max=reg_max,
                )
                if reg_max > 1:
                    fg_dist_logits = distance_logits[bi][fg_mask].view(-1, 4, reg_max)
                    total_dfl_loss = total_dfl_loss + distribution_focal_loss(
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
                    fg_gt_kpts = normalize_gt_keypoints_tensor(
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
                    decoded_kpts_xy = decode_pose_keypoints_xy(
                        pred_xy=pred_kpts_reshaped[..., :2],
                        anchors_xy=fg_anchors,
                        strides=fg_strides,
                        is_pose26=is_pose26,
                    )
                    gt_xy = fg_gt_kpts[..., :2]
                    kpt_mask = build_pose_visibility_mask(
                        torch_module=torch,
                        gt_keypoints=fg_gt_kpts,
                        keypoint_dim=kpt_dim,
                    )
                    area = build_pose_box_area(
                        gt_boxes=fg_gt_boxes,
                    )
                    sigmas = build_pose_oks_sigmas(
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
                        rle_target_weights = build_pose_rle_weights(
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
