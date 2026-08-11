"""YOLOv8 OBB decode。"""

from __future__ import annotations

import math
from typing import Any

import torch
from torch import nn

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.yolo_core_common.geometry import (
    dist2rbox,
    make_anchors,
)

YOLOV8_OBB_ANGLE_DECODE_MODE = "sigmoid-minus-quarter-pi"


def decode_yolov8_obb_angle_logits(*, angle_logits: Any) -> Any:
    """按 YOLOv8 OBB 角度规则解码 angle logits。"""

    return (angle_logits.sigmoid() - 0.25) * math.pi


def build_yolov8_obb_prediction(
    *,
    raw_outputs: dict[str, torch.Tensor],
    strides: tuple[int, ...],
    dfl_decoder: nn.Module,
) -> torch.Tensor:
    """把 YOLOv8 OBB head raw outputs 组装为预测张量。"""

    dfl_distances = dfl_decoder(raw_outputs["boxes"])
    angle = decode_yolov8_obb_angle_logits(angle_logits=raw_outputs["angle"])
    anchor_points, stride_tensor = make_anchors(
        feature_maps=raw_outputs["feats"],
        strides=strides,
    )
    rotated_boxes = dist2rbox(dfl_distances, angle, anchor_points=anchor_points)
    # dist2rbox 返回 feature-grid 坐标；与 Ultralytics Detect._inference 一致，
    # 对外预测必须按每个 anchor 的 stride 恢复到输入图像像素坐标。
    rotated_boxes = rotated_boxes * stride_tensor.transpose(0, 1).unsqueeze(0)
    class_scores = raw_outputs["scores"].sigmoid()
    return torch.cat((rotated_boxes, class_scores, angle), dim=1)


def require_yolov8_obb_angle_decode_mode(mode: str) -> str:
    """校验 YOLOv8 OBB angle decode 模式。"""

    if mode == YOLOV8_OBB_ANGLE_DECODE_MODE:
        return mode
    raise ServiceConfigurationError(
        "当前 YOLOv8 OBB angle decode 模式不受支持",
        details={"mode": mode},
    )


__all__ = [
    "YOLOV8_OBB_ANGLE_DECODE_MODE",
    "build_yolov8_obb_prediction",
    "decode_yolov8_obb_angle_logits",
    "require_yolov8_obb_angle_decode_mode",
]
