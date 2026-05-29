"""Pose（关键点检测）损失计算模块。

复用 detection 的分类/框/DFL 损失，并增加关键点位置损失和可见性损失。
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
    assign_topk: int = 10,
    assign_alpha: float = 0.5,
    assign_beta: float = 6.0,
) -> dict[str, Any]:
    """计算 Pose 完整损失（分类 + 框 + DFL + 关键点位置 + 关键点可见性）。

    参数：
    - model：YOLO 模型（model.model[-1] 为 Pose head）。
    - raw_outputs：训练态原始输出 dict（boxes/scores/kpts/feats）。
    - batch_targets：每个元素包含 boxes_xyxy(N,4)、category_indexes(N,)、
      keypoints(N, K*3)（可选）。
    - num_classes：类别数。
    - kpt_shape：(num_keypoints, dim)，默认 (17, 3)。

    返回：
    - dict 包含 loss、class_loss、box_loss、dfl_loss、kpt_loss。
    """
    from backend.service.application.models.yolo_primary_detection_training import (
        _make_anchors,
        _decode_detection_training_predictions,
        _assign_detection_targets,
        _distribution_focal_loss,
        _box_iou_aligned,
        _bbox_xyxy_to_distances,
    )

    pose_head = model.model[-1]
    reg_max = int(pose_head.reg_max)
    nk = kpt_shape[0]
    kpt_dim = kpt_shape[1]

    # 先复用 detection 解码（boxes + class_logits + anchor_points 等）
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

    # 解码关键点预测 (bs, total_anchors, nk * kpt_dim)
    raw_kpts = raw_outputs.get("kpts")
    if raw_kpts is not None:
        # 原始 kpts shape: (bs, nk * kpt_dim, total_anchors)
        pred_kpts = raw_kpts.permute(0, 2, 1).contiguous()  # (bs, total_anchors, nk*kpt_dim)
    else:
        pred_kpts = None

    bs = class_logits.shape[0]
    total_class_loss = class_logits.new_zeros(())
    total_box_loss = class_logits.new_zeros(())
    total_dfl_loss = class_logits.new_zeros(())
    total_kpt_loss = class_logits.new_zeros(())
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

            # TAL 标签分配（复用 detection 的分配逻辑）
            assignment = _assign_detection_targets(
                torch_module=torch,
                pred_boxes=img_pred_boxes,
                class_probabilities=img_class_probs,
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

                # Box 损失（IoU loss）
                iou_vals = _box_iou_aligned(
                    torch_module=torch, boxes1=fg_pred_boxes, boxes2=fg_gt_boxes,
                ).clamp(0.0, 1.0)
                total_box_loss = total_box_loss + (1.0 - iou_vals).sum()

                # DFL 损失
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
                        torch_module=torch, logits=fg_dist_logits, target=target_distances,
                    ).sum()
                else:
                    fg_dist_logits = distance_logits[bi][fg_mask].view(-1, 4)
                    total_dfl_loss = total_dfl_loss + torch.nn.functional.smooth_l1_loss(
                        torch.nn.functional.softplus(fg_dist_logits), target_distances, reduction="sum",
                    )

                # 关键点损失
                if pred_kpts is not None and gt_kpts is not None and len(gt_kpts) > 0:
                    fg_pred_kpts = pred_kpts[bi][fg_mask]  # (M, nk*kpt_dim)
                    fg_gt_kpts_raw = gt_kpts[fg_assigned]  # list or tensor

                    if isinstance(fg_gt_kpts_raw, list):
                        fg_gt_kpts = torch.tensor(fg_gt_kpts_raw, device=fg_pred_kpts.device, dtype=fg_pred_kpts.dtype)
                    else:
                        fg_gt_kpts = fg_gt_kpts_raw.to(dtype=fg_pred_kpts.dtype)

                    if fg_gt_kpts.dim() == 1:
                        fg_gt_kpts = fg_gt_kpts.unsqueeze(0)

                    # 重塑为 (M, nk, kpt_dim)
                    num_fg = int(fg_pred_kpts.shape[0])
                    pred_kpts_reshaped = fg_pred_kpts.view(num_fg, nk, kpt_dim)

                    if fg_gt_kpts.shape[-1] == nk * kpt_dim:
                        gt_kpts_reshaped = fg_gt_kpts.view(num_fg, nk, kpt_dim)
                    else:
                        gt_kpts_reshaped = fg_gt_kpts.view(num_fg, nk, kpt_dim)

                    # 关键点坐标预测：从 anchor 偏移解码
                    fg_strides = fg_stride.view(-1, 1)
                    fg_anchors = fg_anchor_pts * fg_strides
                    # 预测关键点 = anchor + offset * stride * 2 (sigmoid 映射)
                    pred_xy = pred_kpts_reshaped[..., :2]  # (M, nk, 2)
                    decoded_kpts_xy = fg_anchors.unsqueeze(1) + pred_xy * fg_strides.unsqueeze(1) * 2.0

                    # GT 关键点坐标
                    gt_xy = gt_kpts_reshaped[..., :2]  # (M, nk, 2)

                    # 可见性处理
                    if kpt_dim == 3:
                        gt_vis = gt_kpts_reshaped[..., 2:3]  # (M, nk, 1)，0=未标注, 1=遮挡, 2=可见
                        vis_mask = (gt_vis > 0).float()  # 只计算有标注的关键点
                    else:
                        vis_mask = torch.ones(num_fg, nk, 1, device=fg_pred_kpts.device)

                    # 位置损失（仅对有标注的关键点）
                    kpt_pos_loss = torch.nn.functional.mse_loss(
                        decoded_kpts_xy * vis_mask,
                        gt_xy * vis_mask,
                        reduction="sum",
                    )
                    vis_count = vis_mask.sum().clamp_min(1.0)
                    total_kpt_loss = total_kpt_loss + kpt_pos_loss / vis_count

                total_foreground += int(fg_mask.sum().item())
                total_target_score = total_target_score + quality_scores.sum()

        # 分类损失
        total_class_loss = total_class_loss + torch.nn.functional.binary_cross_entropy_with_logits(
            img_class_logits, target_scores, reduction="sum",
        )

    normalizer = total_target_score.clamp_min(1.0)
    fg_norm = max(total_foreground, 1)
    class_loss = total_class_loss / normalizer
    box_loss = total_box_loss / fg_norm
    dfl_loss = total_dfl_loss / fg_norm
    kpt_loss = total_kpt_loss / fg_norm

    total_loss = (
        class_loss * class_loss_weight
        + box_loss * box_loss_weight
        + dfl_loss * dfl_loss_weight
        + kpt_loss * kpt_loss_weight
    )
    return {
        "loss": total_loss,
        "class_loss": class_loss,
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
        "kpt_loss": kpt_loss,
    }
