"""YOLO OBB 共用 loss 辅助函数。"""

from __future__ import annotations

import math
from typing import Any


def probiou_aligned(torch_module: Any, obb1: Any, obb2: Any) -> Any:
    """计算一一对应的两组旋转框 probiou。

    参数：
    - torch_module：PyTorch 模块。
    - obb1：第一组旋转框，shape 为 ``(N, 5)``，格式为 ``xywhr``。
    - obb2：第二组旋转框，shape 为 ``(N, 5)``，格式为 ``xywhr``。

    返回：
    - shape 为 ``(N,)`` 的 probiou 值。
    """

    eps = 1e-7
    x1, y1 = obb1[..., :2].split(1, dim=-1)
    x2, y2 = obb2[..., :2].split(1, dim=-1)
    a1, b1, c1 = _build_obb_covariance(obb1)
    a2, b2, c2 = _build_obb_covariance(obb2)

    denominator = (a1 + a2) * (b1 + b2) - (c1 + c2).pow(2) + eps
    mean_term = (
        ((a1 + a2) * (y1 - y2).pow(2) + (b1 + b2) * (x1 - x2).pow(2)) / denominator
    ) * 0.25
    cross_term = (((c1 + c2) * (x2 - x1) * (y1 - y2)) / denominator) * 0.5
    det1 = (a1 * b1 - c1.pow(2)).clamp_min(0.0)
    det2 = (a2 * b2 - c2.pow(2)).clamp_min(0.0)
    det_sum = (a1 + a2) * (b1 + b2) - (c1 + c2).pow(2)
    scale_term = (det_sum / (4.0 * (det1 * det2).sqrt() + eps) + eps).log() * 0.5

    bd = (mean_term + cross_term + scale_term).clamp(eps, 100.0)
    hd = (1.0 - (-bd).exp() + eps).sqrt()
    return (1.0 - hd).clamp(0.0, 1.0).squeeze(-1)


def _build_obb_covariance(rboxes: Any) -> tuple[Any, Any, Any]:
    """把 ``xywhr`` 旋转框转换为概率 IoU 使用的协方差三元组。"""

    width = rboxes[..., 2:3].clamp_min(1e-3)
    height = rboxes[..., 3:4].clamp_min(1e-3)
    angle = rboxes[..., 4:5]
    a = width.pow(2) / 12.0
    b = height.pow(2) / 12.0
    cos = angle.cos()
    sin = angle.sin()
    cos2 = cos.pow(2)
    sin2 = sin.pow(2)
    return a * cos2 + b * sin2, a * sin2 + b * cos2, (a - b) * cos * sin


def compute_obb_angle_loss(
    torch_module: Any,
    pred_angle: Any,
    gt_angle: Any,
    gt_wh: Any,
    target_scores: Any,
) -> Any:
    """计算 OBB 角度损失。

    参数：
    - torch_module：PyTorch 模块。
    - pred_angle：预测角度，shape 为 ``(N, 1)``。
    - gt_angle：目标角度，shape 为 ``(N, 1)``。
    - gt_wh：目标宽高，shape 为 ``(N, 2)``。
    - target_scores：正样本质量分数，shape 为 ``(N,)``。

    返回：
    - 标量角度损失。
    """

    if int(pred_angle.shape[0]) == 0:
        return pred_angle.new_zeros(())

    delta = pred_angle - gt_angle
    delta = delta - (delta / math.pi).round() * math.pi
    angle_loss = (2.0 * delta).sin() ** 2

    width = gt_wh[:, 0:1].clamp_min(1e-3)
    height = gt_wh[:, 1:2].clamp_min(1e-3)
    log_aspect_ratio = (width / height).log()
    scale_weight = (-(log_aspect_ratio**2) / (3.0**2)).exp()

    weighted_loss = (angle_loss * scale_weight).squeeze(-1) * target_scores
    return weighted_loss.sum() / target_scores.sum().clamp_min(1.0)
