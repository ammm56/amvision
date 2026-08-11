"""YOLO 主线共用 bbox loss 几何计算。"""

from __future__ import annotations

import math
from typing import Any


def bbox_ciou_matrix(
    *,
    torch_module: Any,
    boxes1: Any,
    boxes2: Any,
    eps: float = 1e-7,
) -> Any:
    """按 Ultralytics bbox_iou(xywh=False, CIoU=True) 计算两两 CIoU。

    CIoU 包含像素坐标差的平方。384 像素的平方已经超过 FP16 最大有限值，
    因此 autocast 训练时必须先提升到 FP32；否则 convex diagonal 和 center
    distance 会同时成为 Inf，并通过 ``Inf / Inf`` 污染 TAL 和全部检测损失。
    该函数刻意返回 FP32，保证 assignment quality 和回归损失继续在稳定精度下
    计算，同时梯度仍可回传到原始预测张量。
    """

    box1 = boxes1.float()[:, None, :]
    box2 = boxes2.float()[None, :, :]
    b1_x1, b1_y1, b1_x2, b1_y2 = box1.chunk(4, dim=-1)
    b2_x1, b2_y1, b2_x2, b2_y2 = box2.chunk(4, dim=-1)
    width1 = b1_x2 - b1_x1
    height1 = b1_y2 - b1_y1 + float(eps)
    width2 = b2_x2 - b2_x1
    height2 = b2_y2 - b2_y1 + float(eps)

    intersection = (
        (b1_x2.minimum(b2_x2) - b1_x1.maximum(b2_x1)).clamp_min(0.0)
        * (b1_y2.minimum(b2_y2) - b1_y1.maximum(b2_y1)).clamp_min(0.0)
    )
    union = width1 * height1 + width2 * height2 - intersection + float(eps)
    iou = intersection / union

    convex_width = b1_x2.maximum(b2_x2) - b1_x1.minimum(b2_x1)
    convex_height = b1_y2.maximum(b2_y2) - b1_y1.minimum(b2_y1)
    convex_diagonal = (
        convex_width.pow(2) + convex_height.pow(2) + float(eps)
    )
    center_distance = (
        (b2_x1 + b2_x2 - b1_x1 - b1_x2).pow(2)
        + (b2_y1 + b2_y2 - b1_y1 - b1_y2).pow(2)
    ) / 4.0
    aspect_penalty = (4.0 / math.pi**2) * (
        (width2 / height2).atan() - (width1 / height1).atan()
    ).pow(2)
    with torch_module.no_grad():
        aspect_weight = aspect_penalty / (
            aspect_penalty - iou + (1.0 + float(eps))
        )
    return (
        iou - (center_distance / convex_diagonal + aspect_weight * aspect_penalty)
    ).squeeze(-1)
