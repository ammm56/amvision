"""YOLO11 core 推理输出适配入口。"""

from backend.service.application.models.yolo11_core.inference.classification import (
    build_yolo11_classification_inference_categories,
    normalize_yolo11_classification_inference_outputs,
)
from backend.service.application.models.yolo11_core.inference.obb import (
    build_yolo11_obb_inference_instances,
    normalize_yolo11_obb_inference_outputs,
)
from backend.service.application.models.yolo11_core.inference.pose import (
    build_yolo11_pose_inference_instances,
    normalize_yolo11_pose_inference_outputs,
)
from backend.service.application.models.yolo11_core.inference.segmentation import (
    build_yolo11_segmentation_inference_instances,
    normalize_yolo11_segmentation_inference_outputs,
)

__all__ = [
    "build_yolo11_classification_inference_categories",
    "build_yolo11_obb_inference_instances",
    "build_yolo11_pose_inference_instances",
    "build_yolo11_segmentation_inference_instances",
    "normalize_yolo11_classification_inference_outputs",
    "normalize_yolo11_obb_inference_outputs",
    "normalize_yolo11_pose_inference_outputs",
    "normalize_yolo11_segmentation_inference_outputs",
]
