"""YOLO11 pose 后处理入口。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.geometry import (
    YoloLetterboxTransform,
    scale_yolo_box_from_letterbox,
    scale_yolo_point_from_letterbox,
)


@dataclass(frozen=True)
class Yolo11PosePostprocessKeypoint:
    """YOLO11 pose 单个关键点后处理结果。"""

    x: float
    y: float
    confidence: float | None


@dataclass(frozen=True)
class Yolo11PosePostprocessInstance:
    """YOLO11 pose 单个实例后处理结果。"""

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None
    keypoints: tuple[Yolo11PosePostprocessKeypoint, ...]
    kpt_shape: tuple[int, int]


def resolve_yolo11_pose_prediction_channel_count(
    *,
    class_count: int,
    keypoint_shape: tuple[int, int],
) -> int:
    """返回 YOLO11 pose 单个候选预测的通道数。"""

    return 4 + int(class_count) + int(keypoint_shape[0]) * int(keypoint_shape[1])


def build_yolo11_pose_postprocess_instances(
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
) -> tuple[tuple[Yolo11PosePostprocessInstance, ...], tuple[int, int]]:
    """把 YOLO11 pose 输出转换为实例记录。"""

    prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    if prediction.ndim == 2:
        prediction = np_module.expand_dims(prediction, axis=0)
    if prediction.ndim < 3:
        raise InvalidRequestError(
            "YOLO11 pose 推理输出维度不合法",
            details={"shape": list(prediction.shape)},
        )

    class_count = len(labels)
    keypoint_width = int(default_kpt_shape[0]) * int(default_kpt_shape[1])
    required_channels = resolve_yolo11_pose_prediction_channel_count(
        class_count=class_count,
        keypoint_shape=default_kpt_shape,
    )
    if _is_yolo11_channel_first_pose_prediction(
        prediction_array=prediction,
        required_channels=required_channels,
    ):
        prediction = np_module.transpose(prediction, (0, 2, 1))
    if int(prediction.shape[2]) < required_channels:
        raise InvalidRequestError(
            "YOLO11 pose 推理输出通道数不足",
            details={
                "channel_count": int(prediction.shape[2]),
                "required_channel_count": required_channels,
            },
        )

    results: list[Yolo11PosePostprocessInstance] = []
    for image_prediction in prediction:
        boxes = _convert_yolo11_pose_xywh_to_xyxy(
            boxes_xywh=image_prediction[:, :4],
            np_module=np_module,
        )
        class_scores = image_prediction[:, 4 : 4 + class_count]
        raw_keypoints = image_prediction[
            :, 4 + class_count : 4 + class_count + keypoint_width
        ]
        best_scores = np_module.max(class_scores, axis=1)
        best_class_ids = np_module.argmax(class_scores, axis=1).astype(
            np_module.int32, copy=False
        )
        keep_mask = best_scores >= score_threshold
        if not bool(np_module.any(keep_mask)):
            continue
        boxes = boxes[keep_mask]
        best_scores = best_scores[keep_mask]
        best_class_ids = best_class_ids[keep_mask]
        raw_keypoints = raw_keypoints[keep_mask]
        keep_indices = nms_indices_func(
            boxes=boxes,
            scores=best_scores,
            class_ids=best_class_ids,
            nms_threshold=nms_threshold,
            np_module=np_module,
        )
        for box, score, class_id, keypoint_row in zip(
            boxes[keep_indices],
            best_scores[keep_indices],
            best_class_ids[keep_indices],
            raw_keypoints[keep_indices],
            strict=True,
        ):
            results.append(
                _build_yolo11_pose_instance(
                    np_module=np_module,
                    box=box,
                    score=score,
                    class_id=int(class_id),
                    keypoint_row=keypoint_row,
                    labels=labels,
                    keypoint_confidence_threshold=keypoint_confidence_threshold,
                    letterbox_transform=letterbox_transform,
                    default_kpt_shape=default_kpt_shape,
                )
            )
    results.sort(key=lambda item: item.score, reverse=True)
    return tuple(results), default_kpt_shape


def _convert_yolo11_pose_xywh_to_xyxy(
    *,
    boxes_xywh: Any,
    np_module: Any,
) -> Any:
    """把 YOLO11 pose 默认 xywh box 转换为 NMS 使用的 xyxy。"""

    center_x = boxes_xywh[:, 0]
    center_y = boxes_xywh[:, 1]
    width = boxes_xywh[:, 2]
    height = boxes_xywh[:, 3]
    half_width = width / 2.0
    half_height = height / 2.0
    return np_module.stack(
        (
            center_x - half_width,
            center_y - half_height,
            center_x + half_width,
            center_y + half_height,
        ),
        axis=1,
    )


def _build_yolo11_pose_instance(
    *,
    np_module: Any,
    box: Any,
    score: float,
    class_id: int,
    keypoint_row: Any,
    labels: tuple[str, ...],
    keypoint_confidence_threshold: float,
    letterbox_transform: YoloLetterboxTransform,
    default_kpt_shape: tuple[int, int],
) -> Yolo11PosePostprocessInstance:
    """构建单个 YOLO11 pose 后处理实例。"""

    scaled_box = scale_yolo_box_from_letterbox(
        box_xyxy=(float(box[0]), float(box[1]), float(box[2]), float(box[3])),
        transform=letterbox_transform,
    )
    if scaled_box is None:
        scaled_box = (0.0, 0.0, 0.0, 0.0)
    x1, y1, x2, y2 = scaled_box
    class_name = labels[class_id] if 0 <= class_id < len(labels) else None
    keypoints: list[Yolo11PosePostprocessKeypoint] = []
    has_confidence = int(default_kpt_shape[1]) > 2
    keypoint_row = np_module.asarray(keypoint_row, dtype=np_module.float32)
    for keypoint_index in range(int(default_kpt_shape[0])):
        base_index = keypoint_index * int(default_kpt_shape[1])
        x_value, y_value = scale_yolo_point_from_letterbox(
            point_xy=(float(keypoint_row[base_index]), float(keypoint_row[base_index + 1])),
            transform=letterbox_transform,
        )
        confidence = (
            float(keypoint_row[base_index + 2])
            if has_confidence and base_index + 2 < int(keypoint_row.shape[0])
            else None
        )
        if confidence is not None and confidence < keypoint_confidence_threshold:
            x_value, y_value = 0.0, 0.0
        keypoints.append(
            Yolo11PosePostprocessKeypoint(
                x=round(x_value, 3),
                y=round(y_value, 3),
                confidence=round(confidence, 6) if confidence is not None else None,
            )
        )
    return Yolo11PosePostprocessInstance(
        bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)),
        score=round(float(score), 6),
        class_id=class_id,
        class_name=class_name,
        keypoints=tuple(keypoints),
        kpt_shape=default_kpt_shape,
    )


def _is_yolo11_channel_first_pose_prediction(
    *,
    prediction_array: Any,
    required_channels: int,
) -> bool:
    """判断 YOLO11 pose prediction 是否为 export 的 [B, C, N] 布局。"""

    if int(prediction_array.ndim) != 3:
        return False
    return int(prediction_array.shape[1]) >= int(required_channels) and int(
        prediction_array.shape[2]
    ) > int(prediction_array.shape[1])


__all__ = [
    "Yolo11PosePostprocessInstance",
    "Yolo11PosePostprocessKeypoint",
    "build_yolo11_pose_postprocess_instances",
    "resolve_yolo11_pose_prediction_channel_count",
]
