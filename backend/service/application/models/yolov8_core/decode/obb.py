"""YOLOv8 OBB decode。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.decode import (
    OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI,
    build_obb_prediction,
    decode_obb_angle_logits,
)


def decode_yolov8_obb_angle_logits(*, angle_logits: Any) -> Any:
    """按 YOLOv8 OBB 角度规则解码 angle logits。"""

    return decode_obb_angle_logits(
        angle_logits=angle_logits,
        mode=OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI,
    )


def build_yolov8_obb_prediction(
    *,
    raw_outputs: dict[str, Any],
    strides: tuple[int, ...],
    dfl_decoder: Any,
) -> Any:
    """把 YOLOv8 OBB head raw outputs 组装为预测张量。"""

    return build_obb_prediction(
        raw_outputs=raw_outputs,
        strides=strides,
        dfl_decoder=dfl_decoder,
        angle_decode_mode=OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI,
    )


__all__ = [
    "build_yolov8_obb_prediction",
    "decode_yolov8_obb_angle_logits",
]
