"""YOLOv8 detection head。"""

from __future__ import annotations

from backend.service.application.models.yolo_core_common.tasks.detection import (
    Detect as _CommonDetect,
)


class Detect(_CommonDetect):
    """YOLOv8 detection head。"""
