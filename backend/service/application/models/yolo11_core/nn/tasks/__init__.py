"""YOLO11 core 任务 head 入口。"""

from __future__ import annotations

from backend.service.application.models.yolo11_core.nn.tasks.classification import (
    Classify,
)
from backend.service.application.models.yolo11_core.nn.tasks.detection import Detect
from backend.service.application.models.yolo11_core.nn.tasks.obb import OBB
from backend.service.application.models.yolo11_core.nn.tasks.pose import Pose
from backend.service.application.models.yolo11_core.nn.tasks.segmentation import (
    Proto,
    Segment,
)

__all__ = [
    "Classify",
    "Detect",
    "OBB",
    "Pose",
    "Proto",
    "Segment",
]
