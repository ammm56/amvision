"""YOLO26 专用任务 head 兼容入口。"""

from __future__ import annotations

from backend.service.application.models.yolo26_core.nn.tasks import (
    OBB26,
    Pose26,
    Proto26,
    RealNVP,
    Segment26,
)

__all__ = [
    "OBB26",
    "Pose26",
    "Proto26",
    "RealNVP",
    "Segment26",
]
