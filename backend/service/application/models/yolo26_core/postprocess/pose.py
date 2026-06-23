"""YOLO26 pose 后处理入口。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo26_core.postprocess.detection import (
    DEFAULT_YOLO26_END2END_MAX_DETECTIONS,
    is_yolo26_processed_class_id_column,
    select_yolo26_end2end_topk_indices,
)


@dataclass(frozen=True)
class Yolo26PosePostprocessKeypoint:
    """YOLO26 pose 单个关键点后处理结果。"""

    x: float
    y: float
    confidence: float | None


@dataclass(frozen=True)
class Yolo26PosePostprocessInstance:
    """YOLO26 pose 单个实例后处理结果。"""

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None
    keypoints: tuple[Yolo26PosePostprocessKeypoint, ...]
    kpt_shape: tuple[int, int]


def resolve_yolo26_pose_prediction_channel_count(
    *,
    class_count: int,
    keypoint_shape: tuple[int, int],
) -> int:
    """返回 YOLO26 pose 单个候选预测的通道数。"""

    return 4 + int(class_count) + int(keypoint_shape[0]) * int(keypoint_shape[1])


def build_yolo26_pose_postprocess_instances(
    *,
    np_module: Any,
    prediction_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    keypoint_confidence_threshold: float,
    resize_ratio: float,
    image_width: int,
    image_height: int,
    input_size: tuple[int, int],
    default_kpt_shape: tuple[int, int],
    nms_threshold: float,
    nms_indices_func: Callable[..., Any],
) -> tuple[tuple[Yolo26PosePostprocessInstance, ...], tuple[int, int]]:
    """把 YOLO26 pose 输出转换为实例记录。"""

    _ = input_size, nms_threshold, nms_indices_func
    prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    if prediction.ndim == 2:
        prediction = np_module.expand_dims(prediction, axis=0)
    if prediction.ndim < 3:
        raise InvalidRequestError(
            "YOLO26 pose 推理输出维度不合法",
            details={"shape": list(prediction.shape)},
        )

    class_count = len(labels)
    keypoint_width = int(default_kpt_shape[0]) * int(default_kpt_shape[1])
    required_channels = resolve_yolo26_pose_prediction_channel_count(
        class_count=class_count,
        keypoint_shape=default_kpt_shape,
    )
    processed_instances = _build_yolo26_pose_processed_instances(
        np_module=np_module,
        prediction=prediction,
        labels=labels,
        score_threshold=score_threshold,
        keypoint_confidence_threshold=keypoint_confidence_threshold,
        resize_ratio=resize_ratio,
        image_width=image_width,
        image_height=image_height,
        default_kpt_shape=default_kpt_shape,
    )
    if processed_instances is not None:
        return processed_instances, default_kpt_shape
    if int(prediction.shape[2]) < required_channels:
        raise InvalidRequestError(
            "YOLO26 pose 推理输出通道数不足",
            details={
                "channel_count": int(prediction.shape[2]),
                "required_channel_count": required_channels,
            },
        )

    results: list[Yolo26PosePostprocessInstance] = []
    for image_prediction in prediction:
        class_scores = image_prediction[:, 4 : 4 + class_count]
        raw_keypoints = image_prediction[
            :, 4 + class_count : 4 + class_count + keypoint_width
        ]
        selected_scores, selected_class_ids, selected_anchor_indices = (
            select_yolo26_end2end_topk_indices(
                np_module=np_module,
                class_scores=class_scores,
                max_detections=DEFAULT_YOLO26_END2END_MAX_DETECTIONS,
            )
        )
        if int(selected_anchor_indices.size) <= 0:
            continue
        keep_mask = selected_scores >= float(score_threshold)
        if not bool(np_module.any(keep_mask)):
            continue
        selected_anchor_indices = selected_anchor_indices[keep_mask]
        boxes = image_prediction[selected_anchor_indices, :4]
        for box, score, class_id, keypoint_row in zip(
            boxes,
            selected_scores[keep_mask],
            selected_class_ids[keep_mask],
            raw_keypoints[selected_anchor_indices],
            strict=True,
        ):
            results.append(
                _build_yolo26_pose_instance(
                    np_module=np_module,
                    box=box,
                    score=score,
                    class_id=int(class_id),
                    keypoint_row=keypoint_row,
                    labels=labels,
                    keypoint_confidence_threshold=keypoint_confidence_threshold,
                    resize_ratio=resize_ratio,
                    image_width=image_width,
                    image_height=image_height,
                    default_kpt_shape=default_kpt_shape,
                )
            )
    results.sort(key=lambda item: item.score, reverse=True)
    return tuple(results), default_kpt_shape


def _build_yolo26_pose_processed_instances(
    *,
    np_module: Any,
    prediction: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    keypoint_confidence_threshold: float,
    resize_ratio: float,
    image_width: int,
    image_height: int,
    default_kpt_shape: tuple[int, int],
) -> tuple[Yolo26PosePostprocessInstance, ...] | None:
    """解析官方 YOLO26 export processed pose 输出。"""

    keypoint_width = int(default_kpt_shape[0]) * int(default_kpt_shape[1])
    required_channels = 6 + keypoint_width
    if int(prediction.shape[1]) > DEFAULT_YOLO26_END2END_MAX_DETECTIONS:
        return None
    if int(prediction.shape[2]) < required_channels:
        return None
    if not is_yolo26_processed_class_id_column(
        np_module=np_module,
        prediction_array=prediction,
        class_column_index=5,
        num_classes=len(labels),
    ):
        return None

    results: list[Yolo26PosePostprocessInstance] = []
    for image_prediction in prediction:
        scores = image_prediction[:, 4]
        keep_mask = scores >= float(score_threshold)
        if not bool(np_module.any(keep_mask)):
            continue
        for box, score, class_id, keypoint_row in zip(
            image_prediction[keep_mask, :4],
            scores[keep_mask],
            image_prediction[keep_mask, 5].astype(np_module.int32, copy=False),
            image_prediction[keep_mask, 6 : 6 + keypoint_width],
            strict=True,
        ):
            results.append(
                _build_yolo26_pose_instance(
                    np_module=np_module,
                    box=box,
                    score=score,
                    class_id=int(class_id),
                    keypoint_row=keypoint_row,
                    labels=labels,
                    keypoint_confidence_threshold=keypoint_confidence_threshold,
                    resize_ratio=resize_ratio,
                    image_width=image_width,
                    image_height=image_height,
                    default_kpt_shape=default_kpt_shape,
                )
            )
    results.sort(key=lambda item: item.score, reverse=True)
    return tuple(results)


def _build_yolo26_pose_instance(
    *,
    np_module: Any,
    box: Any,
    score: float,
    class_id: int,
    keypoint_row: Any,
    labels: tuple[str, ...],
    keypoint_confidence_threshold: float,
    resize_ratio: float,
    image_width: int,
    image_height: int,
    default_kpt_shape: tuple[int, int],
) -> Yolo26PosePostprocessInstance:
    """构建单个 YOLO26 pose 后处理实例。"""

    scaled_box = box / max(resize_ratio, 1e-8)
    x1 = float(max(0.0, min(float(scaled_box[0]), float(image_width))))
    y1 = float(max(0.0, min(float(scaled_box[1]), float(image_height))))
    x2 = float(max(0.0, min(float(scaled_box[2]), float(image_width))))
    y2 = float(max(0.0, min(float(scaled_box[3]), float(image_height))))
    class_name = labels[class_id] if 0 <= class_id < len(labels) else None
    keypoints: list[Yolo26PosePostprocessKeypoint] = []
    has_confidence = int(default_kpt_shape[1]) > 2
    keypoint_row = np_module.asarray(keypoint_row, dtype=np_module.float32)
    for keypoint_index in range(int(default_kpt_shape[0])):
        base_index = keypoint_index * int(default_kpt_shape[1])
        x_value = float(keypoint_row[base_index] / max(resize_ratio, 1e-8))
        y_value = float(keypoint_row[base_index + 1] / max(resize_ratio, 1e-8))
        confidence = (
            float(keypoint_row[base_index + 2])
            if has_confidence and base_index + 2 < int(keypoint_row.shape[0])
            else None
        )
        if confidence is not None and confidence < keypoint_confidence_threshold:
            x_value, y_value = 0.0, 0.0
        keypoints.append(
            Yolo26PosePostprocessKeypoint(
                x=round(x_value, 3),
                y=round(y_value, 3),
                confidence=round(confidence, 6) if confidence is not None else None,
            )
        )
    return Yolo26PosePostprocessInstance(
        bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)),
        score=round(float(score), 6),
        class_id=class_id,
        class_name=class_name,
        keypoints=tuple(keypoints),
        kpt_shape=default_kpt_shape,
    )


__all__ = [
    "Yolo26PosePostprocessInstance",
    "Yolo26PosePostprocessKeypoint",
    "build_yolo26_pose_postprocess_instances",
    "resolve_yolo26_pose_prediction_channel_count",
]
