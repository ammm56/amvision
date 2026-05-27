"""YOLO26 detection 的兼容入口。"""

from __future__ import annotations

from backend.service.application.models.yolo_primary_detection_model import (
    YOLO26_DETECTION_MODEL_CONFIG,
    build_yolo26_detection_model,
    load_yolo_primary_checkpoint,
)


__all__ = (
    "YOLO26_DETECTION_MODEL_CONFIG",
    "build_yolo26_detection_model",
    "load_yolo_primary_checkpoint",
)
