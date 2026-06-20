"""YOLO26 core head 入口。"""

from __future__ import annotations

from backend.service.application.models.yolo26_core.nn.tasks import (
    Classify,
    Detect,
    OBB26,
    Pose26,
    Segment26,
)


YOLO26_HEAD_MODULES = {
    "Detect": Detect,
    "Segment26": Segment26,
    "Pose26": Pose26,
    "OBB26": OBB26,
    "Classify": Classify,
}

__all__ = [
    "Classify",
    "Detect",
    "OBB26",
    "Pose26",
    "Segment26",
    "YOLO26_HEAD_MODULES",
]
