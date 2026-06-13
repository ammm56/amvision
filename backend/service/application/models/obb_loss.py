"""OBB（旋转框）损失计算模块。

实现 probiou、旋转框 TAL 标签分配和完整的 OBB 损失函数，
包含分类损失、框回归损失、DFL 损失和角度损失四个分量。
"""

from __future__ import annotations

import math
from typing import Any


def _probiou_aligned(torch: Any, obb1: Any, obb2: Any) -> Any:
    """计算一一对应的两组旋转框 probiou（概率 IoU）。

    参数：
    - obb1/obb2：shape (N, 5)，格式 xywhr。

    返回：
    - shape (N,) 的 probiou 值。
    """
    x1, y1, w1, h1, a1 = obb1.unbind(dim=-1)
    x2, y2, w2, h2, a2 = obb2.unbind(dim=-1)

    w1 = w1.clamp_min(1e-3)
    h1 = h1.clamp_min(1e-3)
    w2 = w2.clamp_min(1e-3)
    h2 = h2.clamp_min(1e-3)

    # 协方差矩阵 Sigma = R @ diag(w²/4, h²/4) @ R^T
    cos1, sin1 = a1.cos(), a1.sin()
    cos2, sin2 = a2.cos(), a2.sin()

    # Sigma1 元素
    s1_00 = (w1 * cos1) ** 2 + (h1 * sin1) ** 2
    s1_01 = (w1 ** 2 - h1 ** 2) * cos1 * sin1
    s1_11 = (w1 * sin1) ** 2 + (h1 * cos1) ** 2

    # Sigma2 元素
    s2_00 = (w2 * cos2) ** 2 + (h2 * sin2) ** 2
    s2_01 = (w2 ** 2 - h2 ** 2) * cos2 * sin2
    s2_11 = (w2 * sin2) ** 2 + (h2 * cos2) ** 2

    # Sigma_sum = Sigma1 + Sigma2
    sm_00 = s1_00 + s2_00
    sm_01 = s1_01 + s2_01
    sm_11 = s1_11 + s2_11

    # Sigma_sum 逆矩阵 (2x2)
    det_sum = (sm_00 * sm_11 - sm_01 * sm_01).clamp_min(1e-8)
    inv_00 = sm_11 / det_sum
    inv_01 = -sm_01 / det_sum
    inv_11 = sm_00 / det_sum

    # 均值差
    dx = x1 - x2
    dy = y1 - y2

    # Bhattacharyya 距离第一项（均值差）
    d1 = 0.25 * (dx * dx * inv_00 + 2.0 * dx * dy * inv_01 + dy * dy * inv_11)

    # 第二项（行列式比）
    det1 = (w1 * h1).clamp_min(1e-8) ** 2 / 16.0
    det2 = (w2 * h2).clamp_min(1e-8) ** 2 / 16.0
    det_ratio = (det_sum / (2.0 * (det1 * det2).sqrt().clamp_min(1e-8))).clamp_min(1e-8)
    d2 = 0.5 * det_ratio.log()

    bd = (d1 + d2).clamp_min(0.0)
    hd = (1.0 - (-bd).exp()).clamp(0.0, 1.0).sqrt()
    return (1.0 - hd).clamp(0.0, 1.0)


def _dist2rbox(torch: Any, pred_dist: Any, pred_angle: Any, anchor_points: Any) -> Any:
    """把距离分布 + 角度 + 锚点解码为旋转框 xywhr。

    参数：
    - pred_dist：shape (N, 4)，解码后的 ltrb 距离。
    - pred_angle：shape (N, 1)，角度值。
    - anchor_points：shape (N, 2)，锚点坐标。

    返回：
    - shape (N, 5)，格式 xywhr。
    """
    lt, rb = pred_dist.chunk(2, dim=-1)
    cos_a = pred_angle.cos()
    sin_a = pred_angle.sin()
    xf, yf = (rb - lt).chunk(2, dim=-1)
    x = xf * cos_a - yf * sin_a
    y = xf * sin_a + yf * cos_a
    xy = torch.cat([x, y], dim=-1) + anchor_points
    wh = lt + rb
    return torch.cat([xy, wh, pred_angle], dim=-1)


def _rbox2dist(torch: Any, rboxes: Any, anchor_points: Any, stride_tensor: Any, reg_max: int) -> Any:
    """把旋转框 xywhr 转回 DFL 目标距离分布。

    先消除旋转影响，再投影到锚点相对坐标。

    参数：
    - rboxes：shape (N, 5)，格式 xywhr。
    - anchor_points：shape (N, 2)。
    - stride_tensor：shape (N, 1)。
    - reg_max：最大回归值。

    返回：
    - shape (N, 4)，ltrb 距离目标。
    """
    stride = stride_tensor.view(-1, 1).clamp_min(1e-6)
    xy = rboxes[:, :2]
    wh = rboxes[:, 2:4]
    angle = rboxes[:, 4:5]

    # 反旋转：把 gt 中心投影到锚点的旋转坐标系
    offset = xy - anchor_points * stride
    cos_a = angle.cos()
    sin_a = angle.sin()
    dx = offset[:, 0:1] * cos_a + offset[:, 1:2] * sin_a
    dy = -offset[:, 0:1] * sin_a + offset[:, 1:2] * cos_a

    # 从旋转后的中心偏移还原 ltrb
    half_w = wh[:, 0:1] / 2.0
    half_h = wh[:, 1:2] / 2.0
    left = (half_w - dx) / stride
    top = (half_h - dy) / stride
    right = (half_w + dx) / stride
    bottom = (half_h + dy) / stride

    distances = torch.cat([left, top, right, bottom], dim=-1).clamp_min(0.0)
    if reg_max > 1:
        distances = distances.clamp(max=float(reg_max) - 1.0001)
    return distances


def _compute_angle_loss(torch: Any, pred_angle: Any, gt_angle: Any, gt_wh: Any, target_scores: Any) -> Any:
    """计算角度损失。

    使用 sin²(2Δθ) 损失，并基于宽高比对数权重降低近正方形框的角度权重。

    参数：
    - pred_angle：shape (N, 1)，预测角度。
    - gt_angle：shape (N, 1)，目标角度。
    - gt_wh：shape (N, 2)，目标宽高。
    - target_scores：shape (N,)，正样本质量分数。

    返回：
    - 标量角度损失。
    """
    if int(pred_angle.shape[0]) == 0:
        return pred_angle.new_zeros(())

    # 角度差 wrapping 到 [-pi/2, pi/2]
    delta = pred_angle - gt_angle
    delta = delta - (delta / math.pi).round() * math.pi

    # sin²(2Δθ) 损失
    angle_loss = (2.0 * delta).sin() ** 2

    # 宽高比对数权重：近正方形框降低角度权重
    w = gt_wh[:, 0:1].clamp_min(1e-3)
    h = gt_wh[:, 1:2].clamp_min(1e-3)
    log_ar = (w / h).log()
    lam = 3.0
    scale_weight = (-(log_ar ** 2) / (lam ** 2)).exp()

    weighted_loss = (angle_loss * scale_weight).squeeze(-1) * target_scores
    return weighted_loss.sum() / target_scores.sum().clamp_min(1.0)


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
    from backend.service.application.models.yolo_primary_detection_training import (
        _make_anchors,
        _distribution_focal_loss,
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

    # 解码角度
    if hasattr(obb_head, "_decode_angle_logits"):
        pred_angles = obb_head._decode_angle_logits(raw_angle).unsqueeze(-1)
    else:
        pred_angles = (raw_angle.squeeze(1).sigmoid() - 0.25) * math.pi
        pred_angles = pred_angles.unsqueeze(-1)

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
    angle_all = pred_angles.permute(0, 2, 1).contiguous() if pred_angles.dim() == 3 else pred_angles.view(bs, -1, 1)

    # 解码预测旋转框
    anchor_pts_3d = anchor_points.unsqueeze(0).expand(bs, -1, -1)
    pred_rboxes = _dist2rbox(torch, dist_decoded, angle_all, anchor_pts_3d)  # (bs, N, 5)

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
                pair_iou = _probiou_aligned(torch, gt_expanded, pred_expanded).view(num_gt, num_anchors).clamp(0.0, 1.0)

                gt_class_probs = img_class_probs.detach()[:, gt_classes].t().clamp(0.0, 1.0)
                alignment = gt_class_probs.pow(assign_alpha) * pair_iou.pow(assign_beta)

                gt_corners = _xywhr_to_corners(torch, gt_rboxes)
                inside_mask = _anchor_in_rotated_box(torch, anchor_centers_xy, gt_corners)
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
                iou_vals = _probiou_aligned(torch, fg_pred_rboxes, fg_gt_rboxes).clamp(0.0, 1.0)
                total_box_loss = total_box_loss + (1.0 - iou_vals).sum()

                # DFL 损失
                fg_anchor_pts = anchor_points[fg_mask]
                fg_stride = stride_tensor[fg_mask]
                target_dist = _rbox2dist(torch, fg_gt_rboxes, fg_anchor_pts, fg_stride, reg_max)
                if reg_max > 1:
                    fg_dist_logits = dist_logits_all[bi][fg_mask].view(-1, 4, reg_max)
                    total_dfl_loss = total_dfl_loss + _distribution_focal_loss(
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
                total_angle_loss = total_angle_loss + _compute_angle_loss(
                    torch, fg_pred_angle, fg_gt_angle, fg_gt_wh, fg_scores,
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


def _xywhr_to_corners(torch: Any, rboxes: Any) -> Any:
    """把 xywhr 转为四角点坐标。

    参数：
    - rboxes：shape (N, 5)，格式 xywhr。

    返回：
    - shape (N, 4, 2)，四个角点。
    """
    cx, cy, w, h, angle = rboxes.unbind(dim=-1)
    cos_a = angle.cos()
    sin_a = angle.sin()
    hw = w / 2.0
    hh = h / 2.0
    # 四个角点相对于中心的偏移（未旋转）
    dx = torch.stack([-hw, hw, hw, -hw], dim=-1)
    dy = torch.stack([-hh, -hh, hh, hh], dim=-1)
    # 旋转
    rx = dx * cos_a.unsqueeze(-1) - dy * sin_a.unsqueeze(-1)
    ry = dx * sin_a.unsqueeze(-1) + dy * cos_a.unsqueeze(-1)
    corners_x = rx + cx.unsqueeze(-1)
    corners_y = ry + cy.unsqueeze(-1)
    return torch.stack([corners_x, corners_y], dim=-1)


def _anchor_in_rotated_box(torch: Any, anchor_points: Any, corners: Any) -> Any:
    """判断 anchor 是否在旋转框内部（简化版）。

    参数：
    - anchor_points：shape (M, 2)。
    - corners：shape (N, 4, 2)。

    返回：
    - shape (N, M) 的 bool mask。
    """
    num_gt = int(corners.shape[0])
    num_anchors = int(anchor_points.shape[0])
    if num_gt == 0 or num_anchors == 0:
        return torch.zeros(num_gt, num_anchors, dtype=torch.bool, device=anchor_points.device)

    # 用旋转框的轴对齐包围盒做快速检查
    min_xy = corners.min(dim=1).values  # (N, 2)
    max_xy = corners.max(dim=1).values  # (N, 2)
    ax = anchor_points[:, 0].unsqueeze(0)  # (1, M)
    ay = anchor_points[:, 1].unsqueeze(0)
    mask = (
        (ax >= min_xy[:, 0:1]) & (ax <= max_xy[:, 0:1])
        & (ay >= min_xy[:, 1:2]) & (ay <= max_xy[:, 1:2])
    )
    return mask


def xywhr_to_xyxy(torch: Any, rboxes: Any) -> Any:
    """把 xywhr 转为轴对齐的 xyxy 包围盒。

    参数：
    - rboxes：shape (..., 5)，格式 xywhr。

    返回：
    - shape (..., 4)，格式 xyxy。
    """
    corners = _xywhr_to_corners(torch, rboxes.reshape(-1, 5))
    min_xy = corners.min(dim=1).values
    max_xy = corners.max(dim=1).values
    return torch.cat([min_xy, max_xy], dim=-1).view(*rboxes.shape[:-1], 4)
