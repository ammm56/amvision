"""YOLOv8 core inference 输出适配入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.inference.classification import (
    build_yolov8_classification_inference_categories,
    normalize_yolov8_classification_inference_outputs,
)
from backend.service.application.models.yolov8_core.inference.obb import (
    build_yolov8_obb_inference_instances,
    normalize_yolov8_obb_inference_outputs,
)
from backend.service.application.models.yolov8_core.inference.pose import (
    build_yolov8_pose_inference_instances,
    normalize_yolov8_pose_inference_outputs,
)
from backend.service.application.models.yolov8_core.inference.segmentation import (
    build_yolov8_segmentation_inference_instances,
    normalize_yolov8_segmentation_inference_outputs,
)

__all__ = [
    "build_yolov8_classification_inference_categories",
    "build_yolov8_obb_inference_instances",
    "build_yolov8_pose_inference_instances",
    "build_yolov8_segmentation_inference_instances",
    "normalize_yolov8_classification_inference_outputs",
    "normalize_yolov8_obb_inference_outputs",
    "normalize_yolov8_pose_inference_outputs",
    "normalize_yolov8_segmentation_inference_outputs",
]
