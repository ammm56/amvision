"""YOLOv8 assigner 入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.assigners.detection import (
    assign_yolov8_detection_targets,
    yolov8_box_iou_aligned,
    yolov8_box_iou_matrix,
)
from backend.service.application.models.yolov8_core.assigners.obb import (
    assign_yolov8_obb_targets,
)
from backend.service.application.models.yolov8_core.assigners.pose import (
    assign_yolov8_pose_targets,
    yolov8_pose_box_iou_aligned,
)
from backend.service.application.models.yolov8_core.assigners.segmentation import (
    YoloV8SegmentationAssignment,
    assign_yolov8_segmentation_targets,
)

__all__ = [
    "YoloV8SegmentationAssignment",
    "assign_yolov8_detection_targets",
    "assign_yolov8_obb_targets",
    "assign_yolov8_pose_targets",
    "assign_yolov8_segmentation_targets",
    "yolov8_box_iou_aligned",
    "yolov8_box_iou_matrix",
    "yolov8_pose_box_iou_aligned",
]
