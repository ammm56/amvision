"""YOLO26 专用任务 head。"""

from __future__ import annotations

from backend.service.application.models.yolo26_core.tasks.obb import OBB26
from backend.service.application.models.yolo26_core.tasks.pose import Pose26, RealNVP
from backend.service.application.models.yolo26_core.tasks.segmentation import (
    Proto26,
    Segment26,
)

__all__ = [
    "OBB26",
    "Pose26",
    "Proto26",
    "RealNVP",
    "Segment26",
]
