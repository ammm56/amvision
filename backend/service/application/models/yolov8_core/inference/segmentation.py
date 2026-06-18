"""YOLOv8 segmentation inference 输出适配。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.service.application.models.yolo_core_common.postprocess import (
    SegmentationPostprocessInstance,
)
from backend.service.application.models.yolov8_core.postprocess import (
    build_yolov8_segmentation_postprocess_instances,
    normalize_yolov8_segmentation_outputs,
)


def normalize_yolov8_segmentation_inference_outputs(
    *,
    outputs: object,
    np_module: Any,
) -> tuple[Any, Any]:
    """归一化 YOLOv8 segmentation inference 输出。"""

    return normalize_yolov8_segmentation_outputs(outputs=outputs, np_module=np_module)


def build_yolov8_segmentation_inference_instances(
    *,
    cv2_module: Any,
    np_module: Any,
    prediction_array: Any,
    proto_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    nms_threshold: float,
    mask_threshold: float,
    resize_ratio: float,
    image_width: int,
    image_height: int,
    input_size: tuple[int, int],
    nms_indices_func: Callable[..., Any],
) -> tuple[SegmentationPostprocessInstance, ...]:
    """把 YOLOv8 segmentation inference 输出转换为 core 实例记录。"""

    return build_yolov8_segmentation_postprocess_instances(
        cv2_module=cv2_module,
        np_module=np_module,
        prediction_array=prediction_array,
        proto_array=proto_array,
        labels=labels,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        mask_threshold=mask_threshold,
        resize_ratio=resize_ratio,
        image_width=image_width,
        image_height=image_height,
        input_size=input_size,
        nms_indices_func=nms_indices_func,
    )


__all__ = [
    "build_yolov8_segmentation_inference_instances",
    "normalize_yolov8_segmentation_inference_outputs",
]
