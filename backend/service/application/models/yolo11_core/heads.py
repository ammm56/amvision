"""YOLO11 core head 与 decode 入口。"""

from __future__ import annotations

from backend.service.application.models.yolo_detection_model import (
    Classify,
    Detect,
    OBB,
    Pose,
    Segment,
)


YOLO11_HEAD_MODULES = {
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
    "YOLO11_HEAD_MODULES",
]
