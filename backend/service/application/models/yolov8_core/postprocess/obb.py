"""YOLOv8 OBB 后处理入口。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class YoloV8ObbPostprocessInstance:
    """YOLOv8 OBB 单个实例后处理结果。"""

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None
    angle: float


def resolve_yolov8_obb_prediction_channel_count(*, class_count: int) -> int:
    """返回 YOLOv8 OBB 单个候选预测的通道数。"""

    return 5 + int(class_count)


def build_yolov8_obb_postprocess_instances(
    *,
    np_module: Any,
    prediction_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    resize_ratio: float,
    image_width: int,
    image_height: int,
    nms_threshold: float,
    nms_indices_func: Callable[..., Any],
) -> tuple[YoloV8ObbPostprocessInstance, ...]:
    """把 YOLOv8 OBB 输出转换为实例记录。"""

    prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    if prediction.ndim == 2:
        prediction = np_module.expand_dims(prediction, axis=0)
    if prediction.ndim < 3:
        raise InvalidRequestError(
            "YOLOv8 OBB 推理输出维度不合法",
            details={"shape": list(prediction.shape)},
        )
    class_count = len(labels)
    required_channels = resolve_yolov8_obb_prediction_channel_count(
        class_count=class_count,
    )
    if int(prediction.shape[2]) < required_channels:
        raise InvalidRequestError(
            "YOLOv8 OBB 推理输出通道数不足",
            details={
                "channel_count": int(prediction.shape[2]),
                "required_channel_count": required_channels,
            },
        )

    results: list[YoloV8ObbPostprocessInstance] = []
    for image_prediction in prediction:
        boxes = image_prediction[:, :4]
        class_scores = image_prediction[:, 4 : 4 + class_count]
        angles = image_prediction[:, 4 + class_count]
        best_scores = np_module.max(class_scores, axis=1)
        best_class_ids = np_module.argmax(class_scores, axis=1).astype(np_module.int32, copy=False)
        keep_mask = best_scores >= score_threshold
        if not bool(np_module.any(keep_mask)):
            continue
        boxes = boxes[keep_mask]
        best_scores = best_scores[keep_mask]
        best_class_ids = best_class_ids[keep_mask]
        angles = angles[keep_mask]
        keep_indices = nms_indices_func(
            boxes=boxes,
            scores=best_scores,
            class_ids=best_class_ids,
            nms_threshold=nms_threshold,
            np_module=np_module,
        )
        if int(keep_indices.size) <= 0:
            continue
        for box, score, class_id, angle in zip(
            boxes[keep_indices],
            best_scores[keep_indices],
            best_class_ids[keep_indices],
            angles[keep_indices],
            strict=True,
        ):
            results.append(
                _build_yolov8_obb_instance(
                    box=box,
                    score=score,
                    class_id=int(class_id),
                    angle=float(angle),
                    labels=labels,
                    resize_ratio=resize_ratio,
                    image_width=image_width,
                    image_height=image_height,
                )
            )
    results.sort(key=lambda item: item.score, reverse=True)
    return tuple(results)


def _build_yolov8_obb_instance(
    *,
    box: Any,
    score: float,
    class_id: int,
    angle: float,
    labels: tuple[str, ...],
    resize_ratio: float,
    image_width: int,
    image_height: int,
) -> YoloV8ObbPostprocessInstance:
    """构建单个 YOLOv8 OBB 后处理实例。"""

    scaled_box = box / max(resize_ratio, 1e-8)
    x1 = float(max(0.0, min(float(scaled_box[0]), float(image_width))))
    y1 = float(max(0.0, min(float(scaled_box[1]), float(image_height))))
    x2 = float(max(0.0, min(float(scaled_box[2]), float(image_width))))
    y2 = float(max(0.0, min(float(scaled_box[3]), float(image_height))))
    class_name = labels[class_id] if 0 <= class_id < len(labels) else None
    return YoloV8ObbPostprocessInstance(
        bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)),
        score=round(float(score), 6),
        class_id=class_id,
        class_name=class_name,
        angle=round(float(angle), 6),
    )


__all__ = [
    "YoloV8ObbPostprocessInstance",
    "build_yolov8_obb_postprocess_instances",
    "resolve_yolov8_obb_prediction_channel_count",
]
