"""YOLOv8 core 任务配置兼容入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.cfg import (
    YOLOV8_CLASSIFICATION_MODEL_CONFIG,
    YOLOV8_DETECTION_MODEL_CONFIG,
    YOLOV8_MODEL_CONFIGS,
    YOLOV8_OBB_MODEL_CONFIG,
    YOLOV8_POSE_MODEL_CONFIG,
    YOLOV8_SEGMENTATION_MODEL_CONFIG,
    get_yolov8_model_config,
)

__all__ = [
    "YOLOV8_CLASSIFICATION_MODEL_CONFIG",
    "YOLOV8_DETECTION_MODEL_CONFIG",
    "YOLOV8_MODEL_CONFIGS",
    "YOLOV8_OBB_MODEL_CONFIG",
    "YOLOV8_POSE_MODEL_CONFIG",
    "YOLOV8_SEGMENTATION_MODEL_CONFIG",
    "get_yolov8_model_config",
]
