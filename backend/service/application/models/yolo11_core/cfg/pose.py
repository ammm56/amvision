"""YOLO11 pose 模型配置。"""

from __future__ import annotations

from copy import deepcopy

from backend.service.application.models.yolo11_core.cfg.detection import (
    YOLO11_DETECTION_MODEL_CONFIG,
)


YOLO11_POSE_MODEL_CONFIG: dict[str, object] = deepcopy(YOLO11_DETECTION_MODEL_CONFIG)
YOLO11_POSE_MODEL_CONFIG["kpt_shape"] = (17, 3)
YOLO11_POSE_MODEL_CONFIG["head"] = [
    *YOLO11_POSE_MODEL_CONFIG["head"][:-1],  # type: ignore[index]
    ((16, 19, 22), 1, "Pose", ("nc", "kpt_shape")),
]
