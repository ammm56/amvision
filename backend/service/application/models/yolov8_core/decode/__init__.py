"""YOLOv8 decode 入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.decode.detection import (
    build_yolov8_detection_prediction,
    decode_yolov8_detection_boxes,
    decode_yolov8_detection_training_predictions,
)
from backend.service.application.models.yolov8_core.decode.obb import (
    YOLOV8_OBB_ANGLE_DECODE_MODE,
    build_yolov8_obb_prediction,
    decode_yolov8_obb_angle_logits,
    require_yolov8_obb_angle_decode_mode,
)
from backend.service.application.models.yolov8_core.decode.pose import (
    decode_yolov8_pose_keypoints,
    decode_yolov8_pose_keypoints_xy,
)

__all__ = [
    "YOLOV8_OBB_ANGLE_DECODE_MODE",
    "build_yolov8_detection_prediction",
    "build_yolov8_obb_prediction",
    "decode_yolov8_detection_boxes",
    "decode_yolov8_detection_training_predictions",
    "decode_yolov8_obb_angle_logits",
    "decode_yolov8_pose_keypoints",
    "decode_yolov8_pose_keypoints_xy",
    "require_yolov8_obb_angle_decode_mode",
]
