"""YOLO11 OBB 后处理入口。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.evaluation.coco_style_metrics import (
    polygon_bounds_xyxy,
    rotated_iou_xywhr,
    xywhr_to_polygon,
)
from backend.service.application.models.yolo_core_common.postprocess import (
    select_top_scoring_candidate_indices,
)


MAX_YOLO11_OBB_PRE_NMS_CANDIDATES = 300
MAX_YOLO11_OBB_DETECTIONS = 300


@dataclass(frozen=True)
class Yolo11ObbPostprocessInstance:
    """YOLO11 OBB 单个实例后处理结果。"""

    bbox_xyxy: tuple[float, float, float, float]
    bbox_xywhr: tuple[float, float, float, float, float]
    score: float
    class_id: int
    class_name: str | None
    angle: float


def resolve_yolo11_obb_prediction_channel_count(*, class_count: int) -> int:
    """返回 YOLO11 OBB 单个候选预测的通道数。"""

    return 5 + int(class_count)


def build_yolo11_obb_postprocess_instances(
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
) -> tuple[Yolo11ObbPostprocessInstance, ...]:
    """把 YOLO11 OBB 输出转换为实例记录。"""

    _ = nms_indices_func
    prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    if prediction.ndim == 2:
        prediction = np_module.expand_dims(prediction, axis=0)
    if prediction.ndim < 3:
        raise InvalidRequestError(
            "YOLO11 OBB 推理输出维度不合法",
            details={"shape": list(prediction.shape)},
        )

    class_count = len(labels)
    required_channels = resolve_yolo11_obb_prediction_channel_count(
        class_count=class_count,
    )
    if _is_yolo11_channel_first_obb_prediction(
        prediction_array=prediction,
        required_channels=required_channels,
    ):
        prediction = np_module.transpose(prediction, (0, 2, 1))
    if int(prediction.shape[2]) < required_channels:
        raise InvalidRequestError(
            "YOLO11 OBB 推理输出通道数不足",
            details={
                "channel_count": int(prediction.shape[2]),
                "required_channel_count": required_channels,
            },
        )

    results: list[Yolo11ObbPostprocessInstance] = []
    for image_prediction in prediction:
        boxes_xywh = image_prediction[:, :4]
        class_scores = image_prediction[:, 4 : 4 + class_count]
        angles = image_prediction[:, 4 + class_count]
        best_scores = np_module.max(class_scores, axis=1)
        best_class_ids = np_module.argmax(class_scores, axis=1).astype(
            np_module.int32, copy=False
        )
        keep_mask = best_scores >= score_threshold
        if not bool(np_module.any(keep_mask)):
            continue
        boxes_xywh = boxes_xywh[keep_mask]
        best_scores = best_scores[keep_mask]
        best_class_ids = best_class_ids[keep_mask]
        angles = angles[keep_mask]
        top_indices = select_top_scoring_candidate_indices(
            np_module=np_module,
            scores=best_scores,
            max_candidate_count=MAX_YOLO11_OBB_PRE_NMS_CANDIDATES,
        )
        if top_indices is not None:
            boxes_xywh = boxes_xywh[top_indices]
            best_scores = best_scores[top_indices]
            best_class_ids = best_class_ids[top_indices]
            angles = angles[top_indices]
        boxes_xywhr = _build_yolo11_obb_boxes_xywhr(
            np_module=np_module,
            boxes_xywh=boxes_xywh,
            angles=angles,
        )
        keep_indices = _rotated_nms_indices(
            boxes_xywhr=boxes_xywhr,
            scores=best_scores,
            class_ids=best_class_ids,
            nms_threshold=nms_threshold,
            np_module=np_module,
        )
        for box, score, class_id, angle in zip(
            boxes_xywh[keep_indices],
            best_scores[keep_indices],
            best_class_ids[keep_indices],
            angles[keep_indices],
            strict=True,
        ):
            results.append(
                _build_yolo11_obb_instance(
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
    return tuple(results[:MAX_YOLO11_OBB_DETECTIONS])


def _build_yolo11_obb_instance(
    *,
    box_xywh: Any,
    score: float,
    class_id: int,
    angle: float,
    labels: tuple[str, ...],
    resize_ratio: float,
    image_width: int,
    image_height: int,
) -> Yolo11ObbPostprocessInstance:
    """构建单个 YOLO11 OBB 后处理实例。"""

    scaled_box = box_xywh / max(resize_ratio, 1e-8)
    cx = float(max(0.0, min(float(scaled_box[0]), float(image_width))))
    cy = float(max(0.0, min(float(scaled_box[1]), float(image_height))))
    width = float(max(0.0, min(float(scaled_box[2]), float(image_width))))
    height = float(max(0.0, min(float(scaled_box[3]), float(image_height))))
    bbox_xywhr = (cx, cy, width, height, float(angle))
    x1, y1, x2, y2 = _clip_yolo11_obb_bounds(
        bbox_xywhr=bbox_xywhr,
        image_width=image_width,
        image_height=image_height,
    )
    class_name = labels[class_id] if 0 <= class_id < len(labels) else None
    return Yolo11ObbPostprocessInstance(
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


def _build_yolo11_obb_boxes_xywhr(
    *, np_module: Any, boxes_xywh: Any, angles: Any
) -> Any:
    """把 YOLO11 OBB xywh 和 angle 合成 rotated NMS 使用的 xywhr。"""

    boxes = [
        [float(box[0]), float(box[1]), float(box[2]), float(box[3]), float(angle)]
        for box, angle in zip(boxes_xywh, angles, strict=True)
    ]
    return np_module.asarray(boxes, dtype=np_module.float32)


def _rotated_nms_indices(
    *,
    np_module: Any,
    boxes_xywhr: Any,
    scores: Any,
    class_ids: Any,
    nms_threshold: float,
) -> Any:
    """按类别对 YOLO11 OBB rotated IoU 做 NMS。"""

    box_count = int(len(boxes_xywhr))
    if box_count <= 0:
        return np_module.asarray([], dtype=np_module.int64)
    order = np_module.argsort(scores)[::-1]
    suppressed = np_module.zeros(box_count, dtype=bool)
    keep_indices: list[int] = []
    for raw_index in order:
        index = int(raw_index)
        if bool(suppressed[index]):
            continue
        keep_indices.append(index)
        for raw_compare_index in order:
            compare_index = int(raw_compare_index)
            if compare_index == index or bool(suppressed[compare_index]):
                continue
            if int(class_ids[compare_index]) != int(class_ids[index]):
                continue
            overlap = rotated_iou_xywhr(
                boxes_xywhr[index].tolist(),
                boxes_xywhr[compare_index].tolist(),
            )
            if overlap > float(nms_threshold):
                suppressed[compare_index] = True
    return np_module.asarray(keep_indices, dtype=np_module.int64)


def _clip_yolo11_obb_bounds(
    *,
    bbox_xywhr: tuple[float, float, float, float, float],
    image_width: int,
    image_height: int,
) -> tuple[float, float, float, float]:
    """计算并裁剪 YOLO11 OBB 外接 xyxy。"""

    x1, y1, x2, y2 = polygon_bounds_xyxy(xywhr_to_polygon(bbox_xywhr))
    return (
        float(max(0.0, min(x1, float(image_width)))),
        float(max(0.0, min(y1, float(image_height)))),
        float(max(0.0, min(x2, float(image_width)))),
        float(max(0.0, min(y2, float(image_height)))),
    )


def _is_yolo11_channel_first_obb_prediction(
    *,
    prediction_array: Any,
    required_channels: int,
) -> bool:
    """判断 YOLO11 OBB prediction 是否为 export 的 [B, C, N] 布局。"""

    if int(prediction_array.ndim) != 3:
        return False
    return int(prediction_array.shape[1]) >= int(required_channels) and int(
        prediction_array.shape[2]
    ) > int(prediction_array.shape[1])


__all__ = [
    "Yolo11ObbPostprocessInstance",
    "build_yolo11_obb_postprocess_instances",
    "resolve_yolo11_obb_prediction_channel_count",
]
