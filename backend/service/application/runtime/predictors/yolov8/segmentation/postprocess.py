"""YOLOv8 segmentation runtime 结果组装工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolox_core.postprocess import (
    batched_yolox_nms_indices,
)
from backend.service.application.models.yolo_core_common.geometry import (
    YoloLetterboxTransform,
)
from backend.service.application.models.yolov8_core.inference import (
    build_yolov8_segmentation_inference_instances,
)
from backend.service.application.runtime.predictors.yolov8.segmentation.contracts import (
    DEFAULT_YOLOV8_SEGMENTATION_NMS_THRESHOLD,
    YoloV8SegmentationPredictionInstance,
)


def build_yolov8_segmentation_runtime_instances(
    *,
    cv2_module: Any,
    np_module: Any,
    prediction_array: Any,
    proto_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    mask_threshold: float,
    letterbox_transform: YoloLetterboxTransform,
) -> tuple[YoloV8SegmentationPredictionInstance, ...]:
    """把 YOLOv8 segmentation 输出数组转换成平台实例记录。"""

    core_instances = build_yolov8_segmentation_inference_instances(
        cv2_module=cv2_module,
        np_module=np_module,
        prediction_array=prediction_array,
        proto_array=proto_array,
        labels=labels,
        score_threshold=score_threshold,
        nms_threshold=DEFAULT_YOLOV8_SEGMENTATION_NMS_THRESHOLD,
        mask_threshold=mask_threshold,
        letterbox_transform=letterbox_transform,
        nms_indices_func=batched_yolox_nms_indices,
    )
    return tuple(
        YoloV8SegmentationPredictionInstance(
            bbox_xyxy=instance.bbox_xyxy,
            score=instance.score,
            class_id=instance.class_id,
            class_name=instance.class_name,
            segments=instance.segments,
            mask_area=instance.mask_area,
        )
        for instance in core_instances
    )


__all__ = ["build_yolov8_segmentation_runtime_instances"]
