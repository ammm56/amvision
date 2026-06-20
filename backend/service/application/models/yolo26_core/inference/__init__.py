"""YOLO26 core 推理输出适配入口。"""

from backend.service.application.models.yolo26_core.inference.classification import (
    build_yolo26_classification_inference_categories,
    normalize_yolo26_classification_inference_outputs,
)
from backend.service.application.models.yolo26_core.inference.obb import (
    build_yolo26_obb_inference_instances,
    normalize_yolo26_obb_inference_outputs,
)
from backend.service.application.models.yolo26_core.inference.pose import (
    build_yolo26_pose_inference_instances,
    normalize_yolo26_pose_inference_outputs,
)
from backend.service.application.models.yolo26_core.inference.segmentation import (
    build_yolo26_segmentation_inference_instances,
    normalize_yolo26_segmentation_inference_outputs,
)

__all__ = [
    "build_yolo26_classification_inference_categories",
    "build_yolo26_obb_inference_instances",
    "build_yolo26_pose_inference_instances",
    "build_yolo26_segmentation_inference_instances",
    "normalize_yolo26_classification_inference_outputs",
    "normalize_yolo26_obb_inference_outputs",
    "normalize_yolo26_pose_inference_outputs",
    "normalize_yolo26_segmentation_inference_outputs",
]
