"""OBB（旋转框）损失计算模块。

实现 probiou、旋转框 TAL 标签分配和完整的 OBB 损失函数，
包含分类损失、框回归损失、DFL 损失和角度损失四个分量。
"""

from __future__ import annotations

from typing import Any


def compute_obb_loss(
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
    """计算 OBB 完整损失（分类 + 框 + DFL + 角度）。

    参数：
    - model：YOLO 模型（需要 model.model[-1] 为 OBB head）。
    - raw_outputs：训练态原始输出 dict（boxes/scores/angle/feats）。
    - batch_targets：每个元素包含 boxes_xywhr(N,5)、category_indexes(N,)。
    - num_classes：类别数。

    返回：
    - dict 包含 loss、class_loss、box_loss、dfl_loss、angle_loss。
    """
    from backend.service.application.models.yolo_core_common import (
        OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI,
        decode_obb_angle_logits,
        make_anchors as _make_anchors,
    )
    from backend.service.application.models.yolo_core_common.losses import (
        compute_obb_angle_loss,
        distribution_focal_loss,
        probiou_aligned,
    )
    from backend.service.application.models.yolo_core_common.targets import (
        anchor_in_rotated_box,
        decode_distances_to_rboxes,
        rbox_to_distances,
        xywhr_to_corners,
    )

    obb_head = model.model[-1]
    reg_max = int(obb_head.reg_max)

    # 提取原始输出
    raw_boxes = raw_outputs["boxes"]
    raw_scores = raw_outputs["scores"]
    raw_angle = raw_outputs["angle"]
    feats = raw_outputs["feats"]

    # DFL 解码距离
    if reg_max > 1:
        distances = obb_head.dfl(raw_boxes)
    else:
        distances = torch.nn.functional.softplus(raw_boxes)

    # 解码角度。标准 YOLO 和 YOLO26 的角度语义由 head 上的 mode 显式决定。
    angle_decode_mode = getattr(
        obb_head,
        "angle_decode_mode",
        OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI,
    )
    pred_angles = decode_obb_angle_logits(
        angle_logits=raw_angle,
        mode=angle_decode_mode,
    )

    # 生成锚点
    anchor_points, stride_tensor = _make_anchors(
        feature_maps=feats,
        strides=tuple(int(s) for s in obb_head.strides),
    )

    # 解码距离为 ltrb → (bs, 4, total_anchors) → (bs, total_anchors, 4)
    bs = raw_boxes.shape[0]
    dist_decoded = distances.permute(0, 2, 1).contiguous()  # (bs, total_anchors, 4)
    class_logits_all = raw_scores.permute(0, 2, 1).contiguous()  # (bs, total_anchors, nc)
    dist_logits_all = raw_boxes.permute(0, 2, 1).contiguous()  # (bs, total_anchors, 4*reg_max)
    if pred_angles.dim() == 3 and int(pred_angles.shape[1]) == 1:
        angle_all = pred_angles.transpose(1, 2).contiguous()
    elif pred_angles.dim() == 3 and int(pred_angles.shape[2]) == 1:
        angle_all = pred_angles.contiguous()
    elif pred_angles.dim() == 2:
        angle_all = pred_angles.unsqueeze(-1).contiguous()
    else:
        raise ValueError(f"OBB angle 输出 shape 不合法: {tuple(pred_angles.shape)}")

    # 解码预测旋转框
    anchor_pts_3d = anchor_points.unsqueeze(0).expand(bs, -1, -1)
    pred_rboxes = decode_distances_to_rboxes(
        torch_module=torch,
        pred_dist=dist_decoded,
        pred_angle=angle_all,
        anchor_points=anchor_pts_3d,
    )

    anchor_centers_xy = anchor_points * stride_tensor

    total_class_loss = class_logits_all.new_zeros(())
    total_box_loss = class_logits_all.new_zeros(())
    total_dfl_loss = class_logits_all.new_zeros(())
    total_angle_loss = class_logits_all.new_zeros(())
    total_foreground = 0
    total_target_score = class_logits_all.new_zeros(())

    for bi in range(bs):
        img_class_logits = class_logits_all[bi]
        img_class_probs = img_class_logits.sigmoid()
        img_pred_rboxes = pred_rboxes[bi]
        img_angle = angle_all[bi] if angle_all.dim() == 3 else angle_all
        target_scores = torch.zeros_like(img_class_logits)

        target = batch_targets[bi]
        gt_rboxes_list = getattr(target, "boxes_xywhr", None)
        gt_classes_list = getattr(target, "category_indexes", None)

        if gt_rboxes_list is not None and len(gt_rboxes_list) > 0:
            gt_rboxes = torch.tensor(gt_rboxes_list, device=img_pred_rboxes.device, dtype=img_pred_rboxes.dtype)
            gt_classes = torch.tensor(gt_classes_list, device=img_pred_rboxes.device, dtype=torch.long)
            num_gt = int(gt_rboxes.shape[0])
            num_anchors = int(img_pred_rboxes.shape[0])

            # TAL 分配只生成正负样本和质量分数，参考 Ultralytics 使用 detached box/score 进入 assigner。
            # 后面的 box、DFL 和 angle loss 仍使用原始预测，保证梯度只来自真实损失项。
            with torch.no_grad():
                gt_expanded = gt_rboxes.unsqueeze(1).expand(-1, num_anchors, -1).reshape(-1, 5)
                pred_expanded = img_pred_rboxes.detach().unsqueeze(0).expand(num_gt, -1, -1).reshape(-1, 5)
                pair_iou = probiou_aligned(
                    torch_module=torch,
                    obb1=gt_expanded,
                    obb2=pred_expanded,
                ).view(num_gt, num_anchors).clamp(0.0, 1.0)

                gt_class_probs = img_class_probs.detach()[:, gt_classes].t().clamp(0.0, 1.0)
                alignment = gt_class_probs.pow(assign_alpha) * pair_iou.pow(assign_beta)

                gt_corners = xywhr_to_corners(torch_module=torch, rboxes=gt_rboxes)
                inside_mask = anchor_in_rotated_box(
                    torch_module=torch,
                    anchor_points=anchor_centers_xy,
                    corners=gt_corners,
                )
                alignment = alignment * inside_mask.to(alignment.dtype)

                candidate_mask = torch.zeros_like(inside_mask)
                gt_centers = gt_rboxes[:, :2]
                center_dist = torch.cdist(gt_centers, anchor_centers_xy)
                topk_count = min(max(1, assign_topk), num_anchors)

                for gi in range(num_gt):
                    valid = torch.nonzero(alignment[gi] > 0, as_tuple=False).squeeze(1)
                    if int(valid.numel()) == 0:
                        fallback = int(torch.argmin(center_dist[gi]).item())
                        candidate_mask[gi, fallback] = True
                        alignment[gi, fallback] = alignment[gi, fallback].clamp_min(1e-4)
                        continue
                    k = min(topk_count, int(valid.numel()))
                    _, topk_idx = torch.topk(alignment[gi][valid], k=k)
                    candidate_mask[gi, valid[topk_idx]] = True

                matched = alignment * candidate_mask.to(alignment.dtype)
                quality_scores, assigned_gt = matched.max(dim=0)
                fg_mask = quality_scores > 0

            if bool(fg_mask.any()):
                fg_assigned = assigned_gt[fg_mask]
                with torch.no_grad():
                    max_per_gt = matched.max(dim=1).values.clamp_min(1e-6)
                    quality_scores[fg_mask] = (quality_scores[fg_mask] / max_per_gt[fg_assigned]).clamp(0.0, 1.0)

                fg_pred_rboxes = img_pred_rboxes[fg_mask]
                fg_gt_rboxes = gt_rboxes[fg_assigned]

                # Box 损失（probiou）
                iou_vals = probiou_aligned(
                    torch_module=torch,
                    obb1=fg_pred_rboxes,
                    obb2=fg_gt_rboxes,
                ).clamp(0.0, 1.0)
                total_box_loss = total_box_loss + (1.0 - iou_vals).sum()

                # DFL 损失
                fg_anchor_pts = anchor_points[fg_mask]
                fg_stride = stride_tensor[fg_mask]
                target_dist = rbox_to_distances(
                    torch_module=torch,
                    rboxes=fg_gt_rboxes,
                    anchor_points=fg_anchor_pts,
                    stride_tensor=fg_stride,
                    reg_max=reg_max,
                )
                if reg_max > 1:
                    fg_dist_logits = dist_logits_all[bi][fg_mask].view(-1, 4, reg_max)
                    total_dfl_loss = total_dfl_loss + distribution_focal_loss(
                        torch_module=torch, logits=fg_dist_logits, target=target_dist,
                    ).sum()
                else:
                    fg_dist_logits = dist_logits_all[bi][fg_mask].view(-1, 4)
                    total_dfl_loss = total_dfl_loss + torch.nn.functional.smooth_l1_loss(
                        torch.nn.functional.softplus(fg_dist_logits), target_dist, reduction="sum",
                    )

                # 角度损失
                fg_pred_angle = img_angle[fg_mask].view(-1, 1)
                fg_gt_angle = fg_gt_rboxes[:, 4:5]
                fg_gt_wh = fg_gt_rboxes[:, 2:4]
                fg_scores = quality_scores[fg_mask]
                total_angle_loss = total_angle_loss + compute_obb_angle_loss(
                    torch_module=torch,
                    pred_angle=fg_pred_angle,
                    gt_angle=fg_gt_angle,
                    gt_wh=fg_gt_wh,
                    target_scores=fg_scores,
                )

                total_foreground += int(fg_mask.sum().item())
                total_target_score = total_target_score + quality_scores[fg_mask].sum()

                target_scores[fg_mask, gt_classes[fg_assigned]] = quality_scores[fg_mask]

        # 分类损失
        total_class_loss = total_class_loss + torch.nn.functional.binary_cross_entropy_with_logits(
            img_class_logits, target_scores, reduction="sum",
        )

    normalizer = total_target_score.clamp_min(1.0)
    fg_norm = max(total_foreground, 1)
    class_loss = total_class_loss / normalizer
    box_loss = total_box_loss / fg_norm
    dfl_loss = total_dfl_loss / fg_norm
    angle_loss = total_angle_loss / fg_norm

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
