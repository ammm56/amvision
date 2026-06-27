"""YOLOv8 pose inference 输出适配。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.geometry import (
    YoloLetterboxTransform,
)
from backend.service.application.models.yolov8_core.postprocess import (
    YoloV8PosePostprocessInstance,
    build_yolov8_pose_postprocess_instances,
)


def normalize_yolov8_pose_inference_outputs(
    *,
    outputs: object,
    np_module: Any,
) -> Any:
    """归一化 YOLOv8 pose inference 输出。"""

    if isinstance(outputs, list | tuple):
        if not outputs:
            raise InvalidRequestError("YOLOv8 pose inference 输出为空")
        outputs = outputs[0]

    normalized = outputs
    if hasattr(normalized, "detach"):
        normalized = normalized.detach()
    if hasattr(normalized, "cpu"):
        normalized = normalized.cpu()
    if hasattr(normalized, "numpy"):
        normalized = normalized.numpy()
    prediction = np_module.asarray(normalized, dtype=np_module.float32)
    if prediction.ndim == 2:
        prediction = np_module.expand_dims(prediction, axis=0)
    if prediction.ndim < 3:
        raise InvalidRequestError(
            "YOLOv8 pose inference 输出维度不合法",
            details={"shape": list(prediction.shape)},
        )
    return prediction


def build_yolov8_pose_inference_instances(
    *,
    np_module: Any,
    prediction_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    keypoint_confidence_threshold: float,
    letterbox_transform: YoloLetterboxTransform,
    default_kpt_shape: tuple[int, int],
    nms_threshold: float,
    nms_indices_func: Callable[..., Any],
) -> tuple[tuple[YoloV8PosePostprocessInstance, ...], tuple[int, int]]:
    """把 YOLOv8 pose inference 输出转换为 core 实例记录。"""

    return build_yolov8_pose_postprocess_instances(
        np_module=np_module,
        prediction_array=prediction_array,
        labels=labels,
        score_threshold=score_threshold,
        keypoint_confidence_threshold=keypoint_confidence_threshold,
        letterbox_transform=letterbox_transform,
        default_kpt_shape=default_kpt_shape,
        nms_threshold=nms_threshold,
        nms_indices_func=nms_indices_func,
    )


__all__ = [
    "build_yolov8_pose_inference_instances",
    "normalize_yolov8_pose_inference_outputs",
]
