"""YOLOv8 pose runtime 输入图片和预处理工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8_detection_io import (
    load_yolov8_detection_prediction_image,
    preprocess_yolov8_detection_image,
)


load_yolov8_pose_prediction_image = load_yolov8_detection_prediction_image
preprocess_yolov8_pose_image = preprocess_yolov8_detection_image


__all__ = [
    "load_yolov8_pose_prediction_image",
    "preprocess_yolov8_pose_image",
]
