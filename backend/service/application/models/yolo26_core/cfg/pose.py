"""YOLO26 pose 模型配置。"""

from __future__ import annotations

from copy import deepcopy

from backend.service.application.models.yolo26_core.cfg.detection import (
    YOLO26_DETECTION_MODEL_CONFIG,
)


YOLO26_POSE_MODEL_CONFIG: dict[str, object] = deepcopy(YOLO26_DETECTION_MODEL_CONFIG)
YOLO26_POSE_MODEL_CONFIG["kpt_shape"] = (17, 3)
YOLO26_POSE_MODEL_CONFIG["head"] = [
    *YOLO26_POSE_MODEL_CONFIG["head"][:-1],  # type: ignore[index]
    ((16, 19, 22), 1, "Pose26", ("nc", "kpt_shape")),
]
