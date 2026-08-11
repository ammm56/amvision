"""YOLO 主线 pose loss 辅助函数。"""

from __future__ import annotations

from typing import Any


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


def compute_oks_keypoint_loss(
    *,
    torch_module: Any,
    pred_keypoints_xy: Any,
    gt_keypoints_xy: Any,
    keypoint_mask: Any,
    area: Any,
    sigmas: Any,
) -> Any:
    """按 OKS 公式计算关键点位置损失。

    坐标平方和 bbox 面积在 256 像素以上就可能超过 FP16 最大有限值。
    该路径必须固定用 FP32，避免 ``Inf / Inf`` 把 total loss 污染为 NaN。
    """

    pred_xy_float = pred_keypoints_xy.float()
    gt_xy_float = gt_keypoints_xy.float()
    area_float = area.float()
    sigmas_float = sigmas.float()
    distance_sq = (
        (pred_xy_float[..., 0] - gt_xy_float[..., 0]).pow(2)
        + (pred_xy_float[..., 1] - gt_xy_float[..., 1]).pow(2)
    )
    keypoint_mask_float = keypoint_mask.float()
    visible_count = torch_module.sum(keypoint_mask_float, dim=1) + 1e-9
    keypoint_loss_factor = keypoint_mask.shape[1] / visible_count
    oks_denominator = (
        (2 * sigmas_float).pow(2) * (area_float + 1e-9) * 2
    ).clamp_min(1e-9)
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


def build_pose_oks_sigmas(
    *,
    torch_module: Any,
    num_keypoints: int,
    device: Any,
    dtype: Any,
) -> Any:
    """构建当前关键点配置对应的 OKS sigma。"""

    if num_keypoints == len(COCO_KEYPOINT_OKS_SIGMA):
        values = COCO_KEYPOINT_OKS_SIGMA
    else:
        values = tuple(1.0 / max(num_keypoints, 1) for _ in range(num_keypoints))
    return torch_module.tensor(values, device=device, dtype=dtype).view(1, num_keypoints)


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
    """从 matched gt boxes 构建 OKS 所需的 FP32 面积。"""

    boxes_float = gt_boxes.float()
    widths = (boxes_float[:, 2] - boxes_float[:, 0]).clamp_min(1.0)
    heights = (boxes_float[:, 3] - boxes_float[:, 1]).clamp_min(1.0)
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
