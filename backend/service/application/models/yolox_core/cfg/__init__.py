"""YOLOX core 配置入口。"""

from .detection import (
    YOLOX_DEFAULT_INPUT_SIZE,
    YOLOX_SCALE_PROFILES,
    YOLOX_SUPPORTED_MODEL_SCALES,
    YoloXScaleProfile,
    get_yolox_scale_profile,
    resolve_yolox_input_size,
)

__all__ = [
    "YOLOX_DEFAULT_INPUT_SIZE",
    "YOLOX_SCALE_PROFILES",
    "YOLOX_SUPPORTED_MODEL_SCALES",
    "YoloXScaleProfile",
    "get_yolox_scale_profile",
    "resolve_yolox_input_size",
]
