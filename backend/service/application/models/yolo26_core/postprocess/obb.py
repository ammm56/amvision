"""YOLO26 OBB 后处理入口。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.coco_style_metrics import (
    polygon_bounds_xyxy,
    xywhr_to_polygon,
)
from backend.service.application.models.yolo26_core.postprocess.detection import (
    DEFAULT_YOLO26_END2END_MAX_DETECTIONS,
    select_yolo26_end2end_topk_indices,
)


MAX_YOLO26_OBB_DETECTIONS = 300


@dataclass(frozen=True)
class Yolo26ObbPostprocessInstance:
    """YOLO26 OBB 单个实例后处理结果。"""

    bbox_xyxy: tuple[float, float, float, float]
    bbox_xywhr: tuple[float, float, float, float, float]
    score: float
    class_id: int
    class_name: str | None
    angle: float


def resolve_yolo26_obb_prediction_channel_count(*, class_count: int) -> int:
    """返回 YOLO26 OBB 单个候选预测的通道数。"""

    return 5 + int(class_count)


def build_yolo26_obb_postprocess_instances(
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
) -> tuple[Yolo26ObbPostprocessInstance, ...]:
    """把 YOLO26 OBB 输出转换为实例记录。"""

    _ = nms_indices_func, nms_threshold
    prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    if prediction.ndim == 2:
        prediction = np_module.expand_dims(prediction, axis=0)
    if prediction.ndim < 3:
        raise InvalidRequestError(
            "YOLO26 OBB 推理输出维度不合法",
            details={"shape": list(prediction.shape)},
        )

    class_count = len(labels)
    required_channels = resolve_yolo26_obb_prediction_channel_count(
        class_count=class_count,
    )
    processed_instances = _build_yolo26_obb_processed_instances(
        np_module=np_module,
        prediction=prediction,
        labels=labels,
        score_threshold=score_threshold,
        resize_ratio=resize_ratio,
        image_width=image_width,
        image_height=image_height,
    )
    if processed_instances is not None:
        return processed_instances
    if int(prediction.shape[2]) < required_channels:
        raise InvalidRequestError(
            "YOLO26 OBB 推理输出通道数不足",
            details={
                "channel_count": int(prediction.shape[2]),
                "required_channel_count": required_channels,
            },
        )

    results: list[Yolo26ObbPostprocessInstance] = []
    for image_prediction in prediction:
        boxes_xywh = image_prediction[:, :4]
        class_scores = image_prediction[:, 4 : 4 + class_count]
        angles = image_prediction[:, 4 + class_count]
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
        boxes_xywh = boxes_xywh[selected_anchor_indices]
        best_scores = selected_scores[keep_mask]
        best_class_ids = selected_class_ids[keep_mask]
        angles = angles[selected_anchor_indices]
        for box, score, class_id, angle in zip(
            boxes_xywh,
            best_scores,
            best_class_ids,
            angles,
            strict=True,
        ):
            results.append(
                _build_yolo26_obb_instance(
                    box_xywh=box,
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
    return tuple(results[:MAX_YOLO26_OBB_DETECTIONS])


def _build_yolo26_obb_processed_instances(
    *,
    np_module: Any,
    prediction: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    resize_ratio: float,
    image_width: int,
    image_height: int,
) -> tuple[Yolo26ObbPostprocessInstance, ...] | None:
    """解析官方 YOLO26 export processed OBB 输出。"""

    if int(prediction.shape[1]) != DEFAULT_YOLO26_END2END_MAX_DETECTIONS:
        return None
    if int(prediction.shape[2]) != 7:
        return None

    results: list[Yolo26ObbPostprocessInstance] = []
    for image_prediction in prediction:
        scores = image_prediction[:, 4]
        keep_mask = scores >= float(score_threshold)
        if not bool(np_module.any(keep_mask)):
            continue
        for box, score, class_id, angle in zip(
            image_prediction[keep_mask, :4],
            scores[keep_mask],
            image_prediction[keep_mask, 5].astype(np_module.int32, copy=False),
            image_prediction[keep_mask, 6],
            strict=True,
        ):
            results.append(
                _build_yolo26_obb_instance(
                    box_xywh=box,
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
    return tuple(results[:MAX_YOLO26_OBB_DETECTIONS])


def _build_yolo26_obb_instance(
    *,
    box_xywh: Any,
    score: float,
    class_id: int,
    angle: float,
    labels: tuple[str, ...],
    resize_ratio: float,
    image_width: int,
    image_height: int,
) -> Yolo26ObbPostprocessInstance:
    """构建单个 YOLO26 OBB 后处理实例。"""

    scaled_box = box_xywh / max(resize_ratio, 1e-8)
    cx = float(max(0.0, min(float(scaled_box[0]), float(image_width))))
    cy = float(max(0.0, min(float(scaled_box[1]), float(image_height))))
    width = float(max(0.0, min(float(scaled_box[2]), float(image_width))))
    height = float(max(0.0, min(float(scaled_box[3]), float(image_height))))
    bbox_xywhr = (cx, cy, width, height, float(angle))
    x1, y1, x2, y2 = _clip_yolo26_obb_bounds(
        bbox_xywhr=bbox_xywhr,
        image_width=image_width,
        image_height=image_height,
    )
    class_name = labels[class_id] if 0 <= class_id < len(labels) else None
    return Yolo26ObbPostprocessInstance(
        bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)),
        bbox_xywhr=(
            round(cx, 4),
            round(cy, 4),
            round(width, 4),
            round(height, 4),
            round(float(angle), 6),
        ),
        score=round(float(score), 6),
        class_id=class_id,
        class_name=class_name,
        angle=round(float(angle), 6),
    )


def _clip_yolo26_obb_bounds(
    *,
    bbox_xywhr: tuple[float, float, float, float, float],
    image_width: int,
    image_height: int,
) -> tuple[float, float, float, float]:
    """计算并裁剪 YOLO26 OBB 外接 xyxy。"""

    x1, y1, x2, y2 = polygon_bounds_xyxy(xywhr_to_polygon(bbox_xywhr))
    return (
        float(max(0.0, min(x1, float(image_width)))),
        float(max(0.0, min(y1, float(image_height)))),
        float(max(0.0, min(x2, float(image_width)))),
        float(max(0.0, min(y2, float(image_height)))),
    )


__all__ = [
    "Yolo26ObbPostprocessInstance",
    "build_yolo26_obb_postprocess_instances",
    "resolve_yolo26_obb_prediction_channel_count",
]
