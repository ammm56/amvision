"""YOLO11 core 入口。"""

from backend.service.application.models.yolo11_core.config import (
    YOLO11_MODEL_CONFIGS,
    get_yolo11_model_config,
)
from backend.service.application.models.yolo11_core.heads import YOLO11_HEAD_MODULES
from backend.service.application.models.yolo11_core.model import build_yolo11_model

__all__ = [
    "YOLO11_HEAD_MODULES",
    "YOLO11_MODEL_CONFIGS",
    "build_yolo11_model",
    "get_yolo11_model_config",
]
