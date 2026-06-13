"""YOLO 主线共用 decode 入口。"""

from __future__ import annotations

from backend.service.application.models.yolo_core_common.decode.detection import (
    build_detection_prediction,
    decode_detection_boxes,
)

__all__ = [
    "build_detection_prediction",
    "decode_detection_boxes",
]
