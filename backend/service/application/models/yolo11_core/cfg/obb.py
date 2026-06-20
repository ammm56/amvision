"""YOLO11 OBB 模型配置。"""

from __future__ import annotations

from copy import deepcopy

from backend.service.application.models.yolo11_core.cfg.detection import (
    YOLO11_DETECTION_MODEL_CONFIG,
)


YOLO11_OBB_MODEL_CONFIG: dict[str, object] = deepcopy(YOLO11_DETECTION_MODEL_CONFIG)
YOLO11_OBB_MODEL_CONFIG["head"] = [
    *YOLO11_OBB_MODEL_CONFIG["head"][:-1],  # type: ignore[index]
    ((16, 19, 22), 1, "OBB", ("nc", 1)),
]
