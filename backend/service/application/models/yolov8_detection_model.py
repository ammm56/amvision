"""YOLOv8 detection 的兼容入口。"""

from __future__ import annotations

from backend.service.application.models.yolo_primary_detection_model import (
    YOLOV8_DETECTION_MODEL_CONFIG,
    build_yolov8_detection_model,
    load_yolov8_checkpoint,
)


__all__ = (
    "YOLOV8_DETECTION_MODEL_CONFIG",
    "build_yolov8_detection_model",
    "load_yolov8_checkpoint",
)
