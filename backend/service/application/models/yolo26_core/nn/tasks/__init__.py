"""YOLO26 core 任务 head 入口。"""

from __future__ import annotations

from backend.service.application.models.yolo26_core.nn.tasks.classification import (
    Classify,
)
from backend.service.application.models.yolo26_core.nn.tasks.detection import Detect
from backend.service.application.models.yolo26_core.nn.tasks.obb import OBB26
from backend.service.application.models.yolo26_core.nn.tasks.pose import Pose26, RealNVP
from backend.service.application.models.yolo26_core.nn.tasks.segmentation import (
    Proto26,
    Segment26,
)

__all__ = [
    "Classify",
    "Detect",
    "OBB26",
    "Pose26",
    "Proto26",
    "RealNVP",
    "Segment26",
]
