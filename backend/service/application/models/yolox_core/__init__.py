"""项目内 YOLOX core 运行时包。"""

from .cfg import (
    YOLOX_DEFAULT_INPUT_SIZE,
    YOLOX_SCALE_PROFILES,
    YOLOX_SUPPORTED_MODEL_SCALES,
    YoloXScaleProfile,
)
from .data import TrainTransform, ValTransform
from .dependencies import YoloXCoreDependencies, require_yolox_core_dependencies
from .models import YOLOPAFPN, YOLOX, YOLOXHead, build_yolox_detection_model
from .utils import LRScheduler, postprocess
from .weights import load_yolox_checkpoint_file, load_yolox_warm_start_checkpoint

__all__ = [
    "YOLOX_DEFAULT_INPUT_SIZE",
    "YOLOX_SCALE_PROFILES",
    "YOLOX_SUPPORTED_MODEL_SCALES",
    "TrainTransform",
    "ValTransform",
    "YOLOPAFPN",
    "YOLOX",
    "YOLOXHead",
    "YoloXScaleProfile",
    "YoloXCoreDependencies",
    "LRScheduler",
    "build_yolox_detection_model",
    "load_yolox_checkpoint_file",
    "load_yolox_warm_start_checkpoint",
    "postprocess",
    "require_yolox_core_dependencies",
]
