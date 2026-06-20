"""YOLO26 core loss 入口。"""

from __future__ import annotations

from backend.service.application.models.yolo26_core.losses.classification import (
    compute_yolo26_classification_loss,
    normalize_yolo26_classification_training_outputs,
)
from backend.service.application.models.yolo26_core.losses.detection import (
    compute_yolo26_detection_loss,
    yolo26_distribution_focal_loss,
)
from backend.service.application.models.yolo26_core.losses.obb import (
    compute_yolo26_obb_loss,
    yolo26_probiou_aligned,
)
from backend.service.application.models.yolo26_core.losses.pose import (
    build_yolo26_pose_rle_weights,
    compute_yolo26_pose_loss,
    compute_yolo26_rle_loss,
)
from backend.service.application.models.yolo26_core.losses.segmentation import (
    compute_yolo26_segmentation_detection_loss,
    compute_yolo26_segmentation_mask_loss,
    crop_yolo26_segmentation_mask_loss,
    decode_yolo26_segmentation_training_boxes,
)

__all__ = [
    "build_yolo26_pose_rle_weights",
    "compute_yolo26_classification_loss",
    "compute_yolo26_detection_loss",
    "compute_yolo26_obb_loss",
    "compute_yolo26_pose_loss",
    "compute_yolo26_rle_loss",
    "compute_yolo26_segmentation_detection_loss",
    "compute_yolo26_segmentation_mask_loss",
    "crop_yolo26_segmentation_mask_loss",
    "decode_yolo26_segmentation_training_boxes",
    "normalize_yolo26_classification_training_outputs",
    "yolo26_distribution_focal_loss",
    "yolo26_probiou_aligned",
]
