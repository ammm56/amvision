"""YOLOv8 后处理入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.postprocess.classification import (
    build_yolov8_classification_categories,
    ensure_yolov8_probability_array,
)
from backend.service.application.models.yolov8_core.postprocess.detection import (
    build_yolov8_detection_records,
)
from backend.service.application.models.yolov8_core.postprocess.obb import (
    YoloV8ObbPostprocessInstance,
    build_yolov8_obb_postprocess_instances,
    resolve_yolov8_obb_prediction_channel_count,
)
from backend.service.application.models.yolov8_core.postprocess.pose import (
    YoloV8PosePostprocessInstance,
    YoloV8PosePostprocessKeypoint,
    build_yolov8_pose_postprocess_instances,
    resolve_yolov8_pose_prediction_channel_count,
)
from backend.service.application.models.yolov8_core.postprocess.preview import (
    render_yolov8_detection_preview_image,
)
from backend.service.application.models.yolov8_core.postprocess.segmentation import (
    build_yolov8_segmentation_postprocess_instances,
    normalize_yolov8_segmentation_outputs,
    postprocess_yolov8_segmentation_prediction_array,
    prepare_yolov8_segmentation_nms_inputs_array,
)

__all__ = [
    "YoloV8ObbPostprocessInstance",
    "YoloV8PosePostprocessInstance",
    "YoloV8PosePostprocessKeypoint",
    "build_yolov8_classification_categories",
    "build_yolov8_detection_records",
    "build_yolov8_obb_postprocess_instances",
    "build_yolov8_pose_postprocess_instances",
    "build_yolov8_segmentation_postprocess_instances",
    "ensure_yolov8_probability_array",
    "normalize_yolov8_segmentation_outputs",
    "postprocess_yolov8_segmentation_prediction_array",
    "prepare_yolov8_segmentation_nms_inputs_array",
    "render_yolov8_detection_preview_image",
    "resolve_yolov8_obb_prediction_channel_count",
    "resolve_yolov8_pose_prediction_channel_count",
]
