"""YOLO 主线共用 assigner 入口。"""

from __future__ import annotations

from backend.service.application.models.yolo_core_common.assigners.detection import (
    assign_detection_targets,
    box_iou_aligned,
    box_iou_matrix,
)
from backend.service.application.models.yolo_core_common.assigners.segmentation import (
    SegmentationAssignment,
    assign_segmentation_targets,
)

__all__ = [
    "SegmentationAssignment",
    "assign_detection_targets",
    "assign_segmentation_targets",
    "box_iou_aligned",
    "box_iou_matrix",
]
