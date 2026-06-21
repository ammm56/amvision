"""YOLO26 core 任务配置入口。"""

from __future__ import annotations

from backend.service.application.models.yolo26_core.cfg import (
    YOLO26_CLASSIFICATION_MODEL_CONFIG,
    YOLO26_DETECTION_MODEL_CONFIG,
    YOLO26_MODEL_CONFIGS,
    YOLO26_OBB_MODEL_CONFIG,
    YOLO26_POSE_MODEL_CONFIG,
    YOLO26_SEGMENTATION_MODEL_CONFIG,
    get_yolo26_model_config,
)

__all__ = [
    "YOLO26_CLASSIFICATION_MODEL_CONFIG",
    "YOLO26_DETECTION_MODEL_CONFIG",
    "YOLO26_MODEL_CONFIGS",
    "YOLO26_OBB_MODEL_CONFIG",
    "YOLO26_POSE_MODEL_CONFIG",
    "YOLO26_SEGMENTATION_MODEL_CONFIG",
    "get_yolo26_model_config",
]
