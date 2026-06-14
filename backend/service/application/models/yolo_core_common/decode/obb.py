"""YOLO 主线 OBB decode 边界。"""

from __future__ import annotations

import math
from typing import Literal

import torch
from torch import nn

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.yolo_core_common.geometry import (
    dist2rbox,
    make_anchors,
)

OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI = "sigmoid-minus-quarter-pi"
OBB_ANGLE_DECODE_MODE_RAW = "raw"
ObbAngleDecodeMode = Literal["sigmoid-minus-quarter-pi", "raw"]


def decode_obb_angle_logits(
    *,
    angle_logits: torch.Tensor,
    mode: ObbAngleDecodeMode,
) -> torch.Tensor:
    """按指定模式把 OBB 角度分支输出解码成旋转角。"""

    if mode == OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI:
        return (angle_logits.sigmoid() - 0.25) * math.pi
    if mode == OBB_ANGLE_DECODE_MODE_RAW:
        return angle_logits
    raise ServiceConfigurationError(
        "当前 OBB angle decode 模式不受支持",
        details={"mode": mode},
    )


def build_obb_prediction(
    *,
    raw_outputs: dict[str, torch.Tensor],
    strides: tuple[int, ...],
    dfl_decoder: nn.Module,
    angle_decode_mode: ObbAngleDecodeMode,
) -> torch.Tensor:
    """把 OBB head 原始输出组装成推理预测张量。"""

    dfl_distances = dfl_decoder(raw_outputs["boxes"])
    angle = decode_obb_angle_logits(
        angle_logits=raw_outputs["angle"],
        mode=angle_decode_mode,
    )
    anchor_points = make_anchors(
        feature_maps=raw_outputs["feats"],
        strides=strides,
    )[0]
    rotated_boxes = dist2rbox(dfl_distances, angle, anchor_points=anchor_points)
    class_scores = raw_outputs["scores"].sigmoid()
    return torch.cat((rotated_boxes, class_scores, angle), dim=1)
