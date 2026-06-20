"""YOLOv8 OBB runtime 结果组装工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolox_core.postprocess import (
    batched_yolox_nms_indices,
)
from backend.service.application.models.yolov8_core.inference import (
    build_yolov8_obb_inference_instances,
)
from backend.service.application.runtime.contracts.obb import (
    ObbPredictionInstance,
)
from backend.service.application.runtime.predictors.yolov8_obb_contracts import (
    DEFAULT_YOLOV8_OBB_NMS_THRESHOLD,
)


def build_yolov8_obb_runtime_instances(
    *,
    np_module: Any,
    prediction_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    resize_ratio: float,
    image_width: int,
    image_height: int,
) -> tuple[ObbPredictionInstance, ...]:
    """把 YOLOv8 OBB 输出数组转换成平台实例记录。"""

    core_instances = build_yolov8_obb_inference_instances(
        np_module=np_module,
        prediction_array=prediction_array,
        labels=labels,
        score_threshold=score_threshold,
        resize_ratio=resize_ratio,
        image_width=image_width,
        image_height=image_height,
        nms_threshold=DEFAULT_YOLOV8_OBB_NMS_THRESHOLD,
        nms_indices_func=batched_yolox_nms_indices,
    )
    return tuple(
        ObbPredictionInstance(
            bbox_xyxy=instance.bbox_xyxy,
            score=instance.score,
            class_id=instance.class_id,
            class_name=instance.class_name,
            angle=instance.angle,
        )
        for instance in core_instances
    )


__all__ = ["build_yolov8_obb_runtime_instances"]
