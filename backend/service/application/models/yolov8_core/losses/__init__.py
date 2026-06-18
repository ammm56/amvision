"""YOLOv8 loss 入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.losses.detection import (
    compute_yolov8_detection_loss,
    yolov8_distribution_focal_loss,
)
from backend.service.application.models.yolov8_core.losses.classification import (
    compute_yolov8_classification_loss,
    normalize_yolov8_classification_training_outputs,
)
from backend.service.application.models.yolov8_core.losses.obb import compute_yolov8_obb_loss
from backend.service.application.models.yolov8_core.losses.pose import compute_yolov8_pose_loss
from backend.service.application.models.yolov8_core.losses.segmentation import (
    compute_yolov8_segmentation_detection_loss,
    compute_yolov8_segmentation_mask_loss,
    decode_yolov8_segmentation_training_boxes,
)

__all__ = [
    "compute_yolov8_classification_loss",
    "compute_yolov8_detection_loss",
    "compute_yolov8_obb_loss",
    "compute_yolov8_pose_loss",
    "compute_yolov8_segmentation_detection_loss",
    "compute_yolov8_segmentation_mask_loss",
    "decode_yolov8_segmentation_training_boxes",
    "normalize_yolov8_classification_training_outputs",
    "yolov8_distribution_focal_loss",
]
