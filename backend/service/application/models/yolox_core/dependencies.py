"""YOLOX core 依赖加载入口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.yolox_core.data import (
    InfiniteSampler,
    MosaicDetection,
    TrainTransform,
    YoloBatchSampler,
    worker_init_reset_seed,
)
from backend.service.application.models.yolox_core.models import (
    YOLOPAFPN,
    YOLOX,
    YOLOXHead,
)
from backend.service.application.models.yolox_core.utils import (
    LRScheduler,
    ModelEMA,
    postprocess,
)


@dataclass(frozen=True)
class YoloXCoreDependencies:
    """描述 YOLOX core 训练、评估和导出需要的依赖对象。"""

    cv2: Any
    np: Any
    torch: Any
    MosaicDetection: Any
    InfiniteSampler: Any
    TrainTransform: Any
    YoloBatchSampler: Any
    YOLOPAFPN: Any
    YOLOX: Any
    YOLOXHead: Any
    LRScheduler: Any
    ModelEMA: Any
    postprocess: Any
    worker_init_reset_seed: Any
    COCO: Any
    COCOeval: Any


def require_yolox_core_dependencies() -> YoloXCoreDependencies:
    """按需加载 YOLOX core 的第三方依赖与项目内 core 类。"""

    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
        import torch  # type: ignore[import-not-found]
        from pycocotools.coco import COCO  # type: ignore[import-not-found]
        from pycocotools.cocoeval import COCOeval  # type: ignore[import-not-found]
    except ImportError as error:
        raise ServiceConfigurationError(
            "YOLOX core 依赖缺失，至少需要 torch、torchvision、opencv-python、numpy 和 pycocotools"
        ) from error

    return YoloXCoreDependencies(
        cv2=cv2,
        np=np,
        torch=torch,
        MosaicDetection=MosaicDetection,
        InfiniteSampler=InfiniteSampler,
        TrainTransform=TrainTransform,
        YoloBatchSampler=YoloBatchSampler,
        YOLOPAFPN=YOLOPAFPN,
        YOLOX=YOLOX,
        YOLOXHead=YOLOXHead,
        LRScheduler=LRScheduler,
        ModelEMA=ModelEMA,
        postprocess=postprocess,
        worker_init_reset_seed=worker_init_reset_seed,
        COCO=COCO,
        COCOeval=COCOeval,
    )
