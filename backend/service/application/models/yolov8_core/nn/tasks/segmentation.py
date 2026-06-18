"""YOLOv8 segmentation head。"""

from __future__ import annotations

from backend.service.application.models.yolo_core_common.tasks.segmentation import (
    Segment as _CommonSegment,
)


class Segment(_CommonSegment):
    """YOLOv8 segmentation head。"""
