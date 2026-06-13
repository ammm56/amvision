"""YOLOv8 core 入口。"""

from backend.service.application.models.yolov8_core.config import (
    YOLOV8_MODEL_CONFIGS,
    get_yolov8_model_config,
)
from backend.service.application.models.yolov8_core.heads import YOLOV8_HEAD_MODULES
from backend.service.application.models.yolov8_core.model import build_yolov8_model

__all__ = [
    "YOLOV8_HEAD_MODULES",
    "YOLOV8_MODEL_CONFIGS",
    "build_yolov8_model",
    "get_yolov8_model_config",
]
