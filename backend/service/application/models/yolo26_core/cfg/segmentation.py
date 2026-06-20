"""YOLO26 segmentation 模型配置。"""

from __future__ import annotations

from copy import deepcopy

from backend.service.application.models.yolo26_core.cfg.detection import (
    YOLO26_DETECTION_MODEL_CONFIG,
)


YOLO26_SEGMENTATION_MODEL_CONFIG: dict[str, object] = deepcopy(
    YOLO26_DETECTION_MODEL_CONFIG
)
YOLO26_SEGMENTATION_MODEL_CONFIG["head"] = [
    *YOLO26_SEGMENTATION_MODEL_CONFIG["head"][:-1],  # type: ignore[index]
    ((16, 19, 22), 1, "Segment26", ("nc", 32, 256)),
]
