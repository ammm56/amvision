"""YOLO11 assigner 入口。"""

from __future__ import annotations

from backend.service.application.models.yolo11_core.assigners.detection import (
    assign_yolo11_detection_targets,
    yolo11_box_iou_aligned,
    yolo11_box_iou_matrix,
)
from backend.service.application.models.yolo11_core.assigners.obb import (
    assign_yolo11_obb_targets,
)
from backend.service.application.models.yolo11_core.assigners.pose import (
    assign_yolo11_pose_targets,
    yolo11_pose_box_iou_aligned,
)
from backend.service.application.models.yolo11_core.assigners.segmentation import (
    Yolo11SegmentationAssignment,
    assign_yolo11_segmentation_targets,
)

__all__ = [
    "Yolo11SegmentationAssignment",
    "assign_yolo11_detection_targets",
    "assign_yolo11_obb_targets",
    "assign_yolo11_pose_targets",
    "assign_yolo11_segmentation_targets",
    "yolo11_box_iou_aligned",
    "yolo11_box_iou_matrix",
    "yolo11_pose_box_iou_aligned",
]
