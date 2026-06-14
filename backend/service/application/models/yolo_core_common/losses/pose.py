"""YOLO 主线 pose loss 辅助函数。"""

from __future__ import annotations

from typing import Any


POSE26_OKS_SIGMA = (
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
POSE26_RLE_WEIGHT = (
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


def build_pose_oks_sigmas(
    *,
    torch_module: Any,
    num_keypoints: int,
    device: Any,
    dtype: Any,
) -> Any:
    """构建当前关键点配置对应的 OKS sigma。"""

    if num_keypoints == len(POSE26_OKS_SIGMA):
        values = POSE26_OKS_SIGMA
    else:
        values = tuple(1.0 / max(num_keypoints, 1) for _ in range(num_keypoints))
    return torch_module.tensor(values, device=device, dtype=dtype).view(1, num_keypoints)


def build_pose_rle_weights(
    *,
    torch_module: Any,
    num_keypoints: int,
    device: Any,
    dtype: Any,
) -> Any:
    """构建当前关键点配置对应的 RLE 权重。"""

    if num_keypoints == len(POSE26_RLE_WEIGHT):
        values = POSE26_RLE_WEIGHT
    else:
        values = tuple(1.0 for _ in range(num_keypoints))
    return torch_module.tensor(values, device=device, dtype=dtype)


def decode_pose_keypoints_xy(
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


def build_pose_box_area(
    *,
    gt_boxes: Any,
) -> Any:
    """从 matched gt boxes 构建 OKS 所需面积。"""

    widths = (gt_boxes[:, 2] - gt_boxes[:, 0]).clamp_min(1.0)
    heights = (gt_boxes[:, 3] - gt_boxes[:, 1]).clamp_min(1.0)
    return (widths * heights).view(-1, 1)


def build_pose_visibility_mask(
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
