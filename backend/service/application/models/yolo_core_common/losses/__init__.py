"""YOLO 主线共用 loss 入口。"""

from __future__ import annotations

from backend.service.application.models.yolo_core_common.losses.detection import (
    distribution_focal_loss,
)
from backend.service.application.models.yolo_core_common.losses.obb import (
    compute_obb_angle_loss,
    probiou_aligned,
)
from backend.service.application.models.yolo_core_common.losses.pose import (
    build_pose_box_area,
    build_pose_oks_sigmas,
    build_pose_visibility_mask,
    compute_oks_keypoint_loss,
    compute_visibility_loss,
    decode_pose_keypoints_xy,
)
from backend.service.application.models.yolo_core_common.losses.segmentation import (
    compute_segmentation_detection_loss,
    compute_segmentation_mask_loss,
    decode_segmentation_training_boxes,
    segmentation_bbox_iou_aligned,
)

__all__ = [
    "build_pose_box_area",
    "build_pose_oks_sigmas",
    "build_pose_visibility_mask",
    "compute_obb_angle_loss",
    "compute_oks_keypoint_loss",
    "compute_segmentation_detection_loss",
    "compute_segmentation_mask_loss",
    "compute_visibility_loss",
    "decode_pose_keypoints_xy",
    "decode_segmentation_training_boxes",
    "distribution_focal_loss",
    "probiou_aligned",
    "segmentation_bbox_iou_aligned",
]
