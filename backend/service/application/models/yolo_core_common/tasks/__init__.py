"""YOLO 主线共用任务 head。"""

from __future__ import annotations

from backend.service.application.models.yolo_core_common.tasks.classification import Classify
from backend.service.application.models.yolo_core_common.tasks.detection import Detect
from backend.service.application.models.yolo_core_common.tasks.obb import OBB
from backend.service.application.models.yolo_core_common.tasks.pose import Pose
from backend.service.application.models.yolo_core_common.tasks.segmentation import (
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
