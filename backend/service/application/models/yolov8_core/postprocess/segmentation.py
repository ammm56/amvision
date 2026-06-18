"""YOLOv8 segmentation 后处理入口。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.service.application.models.yolo_core_common.postprocess import (
    SegmentationNmsInputArrays,
    SegmentationPostprocessInstance,
    build_segmentation_postprocess_instances,
    normalize_segmentation_outputs,
    postprocess_segmentation_prediction_array,
    prepare_segmentation_nms_inputs_array,
)


def normalize_yolov8_segmentation_outputs(
    *,
    outputs: object,
    np_module: Any,
) -> tuple[Any, Any]:
    """归一化 YOLOv8 segmentation 的 prediction / proto 输出。"""

    return normalize_segmentation_outputs(outputs=outputs, np_module=np_module)


def build_yolov8_segmentation_postprocess_instances(
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
    """把 YOLOv8 segmentation 输出转换为实例记录。"""

    return build_segmentation_postprocess_instances(
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


def prepare_yolov8_segmentation_nms_inputs_array(
    *,
    image_prediction: Any,
    np_module: Any,
    num_classes: int,
    score_threshold: float,
) -> SegmentationNmsInputArrays | None:
    """筛选 YOLOv8 segmentation NMS 候选。"""

    return prepare_segmentation_nms_inputs_array(
        image_prediction=image_prediction,
        np_module=np_module,
        num_classes=num_classes,
        score_threshold=score_threshold,
    )


def postprocess_yolov8_segmentation_prediction_array(
    *,
    prediction_array: Any,
    np_module: Any,
    num_classes: int,
    score_threshold: float,
    nms_threshold: float,
    nms_indices_func: Callable[..., Any],
) -> list[SegmentationNmsInputArrays | None]:
    """执行 YOLOv8 segmentation 阈值过滤与 NMS。"""

    return postprocess_segmentation_prediction_array(
        prediction_array=prediction_array,
        np_module=np_module,
        num_classes=num_classes,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        nms_indices_func=nms_indices_func,
    )
