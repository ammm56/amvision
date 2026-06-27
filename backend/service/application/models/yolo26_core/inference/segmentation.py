"""YOLO26 segmentation inference 输出适配。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.geometry import (
    YoloLetterboxTransform,
)
from backend.service.application.models.yolo26_core.postprocess import (
    Yolo26SegmentationPostprocessInstance,
    build_yolo26_segmentation_postprocess_instances,
    normalize_yolo26_segmentation_outputs,
)


def normalize_yolo26_segmentation_inference_outputs(
    *,
    outputs: object,
    np_module: Any,
) -> tuple[Any, Any]:
    """归一化 YOLO26 segmentation inference 输出。"""

    outputs = unwrap_yolo26_segmentation_runtime_outputs(outputs)
    num_classes = _infer_yolo26_segmentation_num_classes(
        outputs=outputs, np_module=np_module
    )
    return normalize_yolo26_segmentation_outputs(
        outputs=outputs,
        np_module=np_module,
        num_classes=num_classes,
    )


def build_yolo26_segmentation_inference_instances(
    *,
    cv2_module: Any,
    np_module: Any,
    prediction_array: Any,
    proto_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    nms_threshold: float,
    mask_threshold: float,
    letterbox_transform: YoloLetterboxTransform,
    nms_indices_func: Callable[..., Any],
) -> tuple[Yolo26SegmentationPostprocessInstance, ...]:
    """把 YOLO26 segmentation inference 输出转换为 core 实例记录。"""

    return build_yolo26_segmentation_postprocess_instances(
        cv2_module=cv2_module,
        np_module=np_module,
        prediction_array=prediction_array,
        proto_array=proto_array,
        labels=labels,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        mask_threshold=mask_threshold,
        letterbox_transform=letterbox_transform,
        nms_indices_func=nms_indices_func,
    )


def unwrap_yolo26_segmentation_runtime_outputs(outputs: object) -> object:
    """解开 YOLO26 segmentation 参考 forward 形态中的 processed/raw 双输出。"""

    if (
        isinstance(outputs, list | tuple)
        and len(outputs) >= 2
        and isinstance(outputs[0], list | tuple)
        and len(outputs[0]) >= 2
        and isinstance(outputs[1], dict)
    ):
        return outputs[0]
    return outputs


def _infer_yolo26_segmentation_num_classes(*, outputs: object, np_module: Any) -> int:
    """根据 prediction 与 proto 通道数推断类别数。"""

    if not isinstance(outputs, list | tuple) or len(outputs) < 2:
        raise InvalidRequestError(
            "YOLO26 segmentation 推理输出缺少 prediction/proto 双输出"
        )
    prediction_array = np_module.asarray(outputs[0])
    proto_array = np_module.asarray(outputs[1])
    proto_channels = _infer_yolo26_proto_channels(proto_array=proto_array)
    if prediction_array.ndim == 2:
        prediction_array = np_module.expand_dims(prediction_array, axis=0)
    if prediction_array.ndim != 3:
        raise InvalidRequestError(
            "YOLO26 segmentation prediction 输出维度不合法",
            details={"shape": list(prediction_array.shape)},
        )

    channel_candidates = (
        int(prediction_array.shape[1]),
        int(prediction_array.shape[2]),
    )
    valid_candidates = [
        channel_count - 4 - proto_channels
        for channel_count in channel_candidates
        if channel_count > 4 + proto_channels
    ]
    if not valid_candidates:
        raise InvalidRequestError(
            "YOLO26 segmentation prediction 通道数无法推断类别数",
            details={
                "prediction_shape": list(prediction_array.shape),
                "proto_shape": list(proto_array.shape),
                "proto_channels": proto_channels,
            },
        )
    return min(valid_candidates)


def _infer_yolo26_proto_channels(*, proto_array: Any) -> int:
    """读取 proto 的 mask 通道数。"""

    if proto_array.ndim == 3:
        return int(proto_array.shape[0])
    if proto_array.ndim == 4:
        return int(proto_array.shape[1])
    raise InvalidRequestError(
        "YOLO26 segmentation proto 输出维度不合法",
        details={"shape": list(proto_array.shape)},
    )


__all__ = [
    "build_yolo26_segmentation_inference_instances",
    "normalize_yolo26_segmentation_inference_outputs",
    "unwrap_yolo26_segmentation_runtime_outputs",
]
