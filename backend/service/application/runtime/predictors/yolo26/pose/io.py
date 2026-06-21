"""YOLO26 pose runtime 输入图片和预处理工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.common.yolo_runtime_io import (
    load_yolo_runtime_prediction_image,
    preprocess_yolo_runtime_letterbox_image,
)


load_yolo26_pose_prediction_image = load_yolo_runtime_prediction_image
preprocess_yolo26_pose_image = preprocess_yolo_runtime_letterbox_image


__all__ = [
    "load_yolo26_pose_prediction_image",
    "preprocess_yolo26_pose_image",
]
