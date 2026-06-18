"""YOLO26 pose 专属 loss 辅助函数。"""

from __future__ import annotations

from typing import Any


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
    "compute_yolo26_rle_loss",
]
