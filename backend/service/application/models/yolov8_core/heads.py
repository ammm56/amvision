"""YOLOv8 core head 与 decode 入口。"""

from __future__ import annotations

from backend.service.application.models.yolo_core_common.tasks import (
    Classify,
    Detect,
    OBB,
    Pose,
    Segment,
)


YOLOV8_HEAD_MODULES = {
    "Detect": Detect,
    "Segment": Segment,
    "Pose": Pose,
    "OBB": OBB,
    "Classify": Classify,
}

__all__ = [
    "Classify",
    "Detect",
    "OBB",
    "Pose",
    "Segment",
    "YOLOV8_HEAD_MODULES",
]
