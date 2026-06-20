"""YOLO11 loss 入口。"""

from __future__ import annotations

from backend.service.application.models.yolo11_core.losses.detection import (
    compute_yolo11_detection_loss,
    yolo11_distribution_focal_loss,
)
from backend.service.application.models.yolo11_core.losses.obb import (
    compute_yolo11_obb_loss,
    yolo11_probiou_aligned,
)
from backend.service.application.models.yolo11_core.losses.pose import (
    compute_yolo11_pose_loss,
)
from backend.service.application.models.yolo11_core.losses.classification import (
    compute_yolo11_classification_loss,
    normalize_yolo11_classification_training_outputs,
)
from backend.service.application.models.yolo11_core.losses.segmentation import (
    compute_yolo11_segmentation_detection_loss,
    compute_yolo11_segmentation_mask_loss,
    decode_yolo11_segmentation_training_boxes,
)

__all__ = [
    "compute_yolo11_classification_loss",
    "compute_yolo11_detection_loss",
    "compute_yolo11_obb_loss",
    "compute_yolo11_pose_loss",
    "compute_yolo11_segmentation_detection_loss",
    "compute_yolo11_segmentation_mask_loss",
    "decode_yolo11_segmentation_training_boxes",
    "normalize_yolo11_classification_training_outputs",
    "yolo11_distribution_focal_loss",
    "yolo11_probiou_aligned",
]
