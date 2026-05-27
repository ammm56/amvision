"""YOLO11 detection 的兼容入口。"""

from __future__ import annotations

from backend.service.application.models.yolo_primary_detection_model import (
    YOLO11_DETECTION_MODEL_CONFIG,
    build_yolo11_detection_model,
    load_yolo_primary_checkpoint,
)


__all__ = (
    "YOLO11_DETECTION_MODEL_CONFIG",
    "build_yolo11_detection_model",
    "load_yolo_primary_checkpoint",
)
