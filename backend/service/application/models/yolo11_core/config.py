"""YOLO11 core 任务配置兼容入口。"""

from __future__ import annotations

from backend.service.application.models.yolo11_core.cfg import (
    YOLO11_CLASSIFICATION_MODEL_CONFIG,
    YOLO11_DETECTION_MODEL_CONFIG,
    YOLO11_MODEL_CONFIGS,
    YOLO11_OBB_MODEL_CONFIG,
    YOLO11_POSE_MODEL_CONFIG,
    YOLO11_SEGMENTATION_MODEL_CONFIG,
    get_yolo11_model_config,
)

__all__ = [
    "YOLO11_CLASSIFICATION_MODEL_CONFIG",
    "YOLO11_DETECTION_MODEL_CONFIG",
    "YOLO11_MODEL_CONFIGS",
    "YOLO11_OBB_MODEL_CONFIG",
    "YOLO11_POSE_MODEL_CONFIG",
    "YOLO11_SEGMENTATION_MODEL_CONFIG",
    "get_yolo11_model_config",
]
