"""YOLOv8 core 网络模块入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.nn.tasks import (
    Classify,
    Detect,
    OBB,
    Pose,
    Segment,
)

__all__ = [
    "Classify",
    "Detect",
    "OBB",
    "Pose",
    "Segment",
]
