"""YOLO26 detection 后处理入口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.postprocess.detection import (
    DetectionBoxFormat,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionDetection,
)


YOLO26_DETECTION_POSTPROCESS_MODE_END2END_TOPK = "end2end-topk"
DEFAULT_YOLO26_END2END_MAX_DETECTIONS = 300


@dataclass(frozen=True)
class Yolo26DetectionTopKResult:
    """描述单张图片经过 YOLO26 end2end top-k 后的 detection 结果。"""

    boxes_xyxy: Any
    scores: Any
    class_ids: Any


def build_yolo26_detection_records(
    *,
    np_module: Any,
    prediction_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    nms_threshold: float,
    resize_ratio: float,
    image_width: int,
    image_height: int,
    max_detections: int | None = None,
) -> tuple[DetectionPredictionDetection, ...]:
    """把 YOLO26 detection 输出转换成平台 detection 记录。"""

    _ = nms_threshold
    postprocess_results = postprocess_yolo26_detection_prediction_array(
        prediction_array=prediction_array,
        np_module=np_module,
        num_classes=len(labels),
        score_threshold=score_threshold,
        box_format="xyxy",
        max_detections=max_detections,
    )
    if not postprocess_results:
        return ()

    prediction = postprocess_results[0]
    if prediction is None:
        return ()

    detections: list[DetectionPredictionDetection] = []
    for bbox, score, class_id in zip(
        prediction.boxes_xyxy,
        prediction.scores,
        prediction.class_ids,
        strict=True,
    ):
        scaled_bbox = bbox / max(resize_ratio, 1e-8)
        x1 = float(max(0.0, min(float(scaled_bbox[0]), float(image_width))))
        y1 = float(max(0.0, min(float(scaled_bbox[1]), float(image_height))))
        x2 = float(max(0.0, min(float(scaled_bbox[2]), float(image_width))))
        y2 = float(max(0.0, min(float(scaled_bbox[3]), float(image_height))))
        resolved_class_id = int(class_id)
        class_name = (
            labels[resolved_class_id] if 0 <= resolved_class_id < len(labels) else None
        )
        detections.append(
            DetectionPredictionDetection(
                bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)),
                score=round(float(score), 6),
                class_id=resolved_class_id,
                class_name=class_name,
            )
        )
    detections.sort(key=lambda item: item.score, reverse=True)
    return tuple(detections)


def postprocess_yolo26_detection_prediction_array(
    *,
    prediction_array: Any,
    np_module: Any,
    num_classes: int,
    score_threshold: float,
    box_format: DetectionBoxFormat = "xyxy",
    max_detections: int | None = None,
) -> list[Yolo26DetectionTopKResult | None]:
    """按 YOLO26 end2end 参考实现执行 two-stage top-k 后处理。

    Ultralytics 的 end2end Detect 不走 NMS。它先按每个 anchor 的最大类别分数取
    top-k anchor，再在这些 anchor 的所有类别分数里取最终 top-k。平台保留 raw tensor
    导出形态，因此这里在 core 后处理里复现这一段选择逻辑。
    """

    normalized_prediction = _normalize_yolo26_detection_prediction_array(
        prediction_array=prediction_array,
        np_module=np_module,
        num_classes=num_classes,
    )
    resolved_max_detections = max(
        1,
        int(max_detections or DEFAULT_YOLO26_END2END_MAX_DETECTIONS),
    )
    processed_results = _postprocess_yolo26_detection_processed_array(
        prediction_array=normalized_prediction,
        np_module=np_module,
        num_classes=num_classes,
        score_threshold=score_threshold,
        max_detections=resolved_max_detections,
    )
    if processed_results is not None:
        return processed_results

    results: list[Yolo26DetectionTopKResult | None] = []
    for image_prediction in normalized_prediction:
        result = _postprocess_single_yolo26_detection_prediction(
            image_prediction=image_prediction,
            np_module=np_module,
            num_classes=num_classes,
            score_threshold=score_threshold,
            box_format=box_format,
            max_detections=resolved_max_detections,
        )
        results.append(result)
    return results


def _postprocess_yolo26_detection_processed_array(
    *,
    prediction_array: Any,
    np_module: Any,
    num_classes: int,
    score_threshold: float,
    max_detections: int,
) -> list[Yolo26DetectionTopKResult | None] | None:
    """解析官方 YOLO26 export processed detection 输出。"""

    if int(prediction_array.shape[1]) > int(max_detections):
        return None
    if int(prediction_array.shape[2]) != 6:
        return None
    if not is_yolo26_processed_class_id_column(
        np_module=np_module,
        prediction_array=prediction_array,
        class_column_index=5,
        num_classes=num_classes,
    ):
        return None

    results: list[Yolo26DetectionTopKResult | None] = []
    for image_prediction in prediction_array:
        scores = image_prediction[:, 4]
        keep_mask = scores >= float(score_threshold)
        if not bool(np_module.any(keep_mask)):
            results.append(None)
            continue
        boxes_xyxy = normalize_yolo26_detection_boxes_array(
            boxes=image_prediction[keep_mask, :4],
            np_module=np_module,
            box_format="xyxy",
        )
        results.append(
            Yolo26DetectionTopKResult(
                boxes_xyxy=boxes_xyxy,
                scores=scores[keep_mask],
                class_ids=image_prediction[keep_mask, 5].astype(
                    np_module.int32,
                    copy=False,
                ),
            )
        )
    return results


def _postprocess_single_yolo26_detection_prediction(
    *,
    image_prediction: Any,
    np_module: Any,
    num_classes: int,
    score_threshold: float,
    box_format: DetectionBoxFormat,
    max_detections: int,
) -> Yolo26DetectionTopKResult | None:
    """处理单张图片的 YOLO26 end2end detection 预测。"""

    _validate_yolo26_detection_channel_count(
        channel_count=int(image_prediction.shape[1]),
        num_classes=num_classes,
    )
    anchor_count = int(image_prediction.shape[0])
    if anchor_count <= 0:
        return None

    boxes = image_prediction[:, :4]
    scores = image_prediction[:, 4 : 4 + int(num_classes)]
    selected_scores, selected_class_ids, selected_anchor_indices = (
        select_yolo26_end2end_topk_indices(
            np_module=np_module,
            class_scores=scores,
            max_detections=max_detections,
        )
    )
    if int(selected_anchor_indices.size) <= 0:
        return None
    keep_mask = selected_scores >= float(score_threshold)
    if not bool(np_module.any(keep_mask)):
        return None

    selected_boxes = normalize_yolo26_detection_boxes_array(
        boxes=boxes[selected_anchor_indices[keep_mask]],
        np_module=np_module,
        box_format=box_format,
    )
    return Yolo26DetectionTopKResult(
        boxes_xyxy=selected_boxes,
        scores=selected_scores[keep_mask],
        class_ids=selected_class_ids[keep_mask],
    )


def _normalize_yolo26_detection_prediction_array(
    *,
    prediction_array: Any,
    np_module: Any,
    num_classes: int,
) -> Any:
    """把 YOLO26 detection 输出统一成 ``[B, N, C]``。"""

    normalized_prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    if normalized_prediction.ndim == 2:
        normalized_prediction = np_module.expand_dims(normalized_prediction, axis=0)
    if normalized_prediction.ndim < 3:
        raise InvalidRequestError(
            "YOLO26 detection 推理输出维度不合法",
            details={"shape": list(normalized_prediction.shape)},
        )

    required_channel_count = 4 + int(num_classes)
    channel_axis_size = int(normalized_prediction.shape[1])
    last_axis_size = int(normalized_prediction.shape[2])
    if (
        last_axis_size == 6
        and channel_axis_size <= DEFAULT_YOLO26_END2END_MAX_DETECTIONS
    ):
        return normalized_prediction
    if channel_axis_size >= required_channel_count and (
        last_axis_size < required_channel_count or last_axis_size > channel_axis_size
    ):
        normalized_prediction = np_module.transpose(normalized_prediction, (0, 2, 1))

    _validate_yolo26_detection_channel_count(
        channel_count=int(normalized_prediction.shape[2]),
        num_classes=num_classes,
    )
    return normalized_prediction


def select_yolo26_end2end_topk_indices(
    *,
    np_module: Any,
    class_scores: Any,
    max_detections: int | None = None,
) -> tuple[Any, Any, Any]:
    """按 YOLO26 end2end 规则返回 top-k 分数、类别和 anchor 索引。"""

    resolved_max_detections = max(
        1,
        int(max_detections or DEFAULT_YOLO26_END2END_MAX_DETECTIONS),
    )
    anchor_count = int(class_scores.shape[0])
    class_count = int(class_scores.shape[1])
    if anchor_count <= 0 or class_count <= 0:
        empty_float = np_module.asarray([], dtype=np_module.float32)
        empty_int = np_module.asarray([], dtype=np_module.int64)
        return empty_float, empty_int, empty_int

    first_stage_k = min(resolved_max_detections, anchor_count)
    anchor_scores = np_module.max(class_scores, axis=1)
    top_anchor_indices = _select_descending_topk_indices(
        np_module=np_module,
        scores=anchor_scores,
        top_k=first_stage_k,
    )
    if int(top_anchor_indices.size) <= 0:
        empty_float = np_module.asarray([], dtype=np_module.float32)
        empty_int = np_module.asarray([], dtype=np_module.int64)
        return empty_float, empty_int, empty_int

    top_anchor_scores = class_scores[top_anchor_indices]
    flattened_scores = top_anchor_scores.reshape(-1)
    second_stage_k = min(resolved_max_detections, int(flattened_scores.shape[0]))
    final_flat_indices = _select_descending_topk_indices(
        np_module=np_module,
        scores=flattened_scores,
        top_k=second_stage_k,
    )
    selected_anchor_offsets = final_flat_indices // class_count
    selected_class_ids = (final_flat_indices % class_count).astype(
        np_module.int32,
        copy=False,
    )
    return (
        flattened_scores[final_flat_indices],
        selected_class_ids,
        top_anchor_indices[selected_anchor_offsets],
    )


def normalize_yolo26_detection_boxes_array(
    *,
    boxes: Any,
    np_module: Any,
    box_format: DetectionBoxFormat,
) -> Any:
    """把 YOLO26 detection box 转成平台统一使用的 ``xyxy``。"""

    if box_format == "xyxy":
        return normalize_yolo26_xyxy_box_order_array(
            boxes=boxes,
            np_module=np_module,
        )
    if box_format == "xywh":
        center_x = boxes[:, 0]
        center_y = boxes[:, 1]
        width = boxes[:, 2]
        height = boxes[:, 3]
        half_width = width / 2.0
        half_height = height / 2.0
        converted_boxes = np_module.stack(
            (
                center_x - half_width,
                center_y - half_height,
                center_x + half_width,
                center_y + half_height,
            ),
            axis=1,
        )
        return normalize_yolo26_xyxy_box_order_array(
            boxes=converted_boxes,
            np_module=np_module,
        )
    raise InvalidRequestError(
        "当前 YOLO26 detection box 格式不受支持",
        details={"box_format": box_format},
    )


def normalize_yolo26_xyxy_box_order_array(
    *,
    boxes: Any,
    np_module: Any,
) -> Any:
    """保证 YOLO26 输出的 xyxy 坐标满足 x2>=x1 且 y2>=y1。"""

    normalized_boxes = np_module.asarray(boxes, dtype=np_module.float32)
    if int(normalized_boxes.size) <= 0:
        return normalized_boxes
    x1 = np_module.minimum(normalized_boxes[:, 0], normalized_boxes[:, 2])
    y1 = np_module.minimum(normalized_boxes[:, 1], normalized_boxes[:, 3])
    x2 = np_module.maximum(normalized_boxes[:, 0], normalized_boxes[:, 2])
    y2 = np_module.maximum(normalized_boxes[:, 1], normalized_boxes[:, 3])
    return np_module.stack((x1, y1, x2, y2), axis=1)


def is_yolo26_processed_class_id_column(
    *,
    np_module: Any,
    prediction_array: Any,
    class_column_index: int,
    num_classes: int,
) -> bool:
    """判断 YOLO26 processed 输出中的 class id 列是否有效。"""

    if int(prediction_array.shape[2]) <= int(class_column_index):
        return False
    class_values = prediction_array[..., int(class_column_index)]
    if int(class_values.size) <= 0:
        return True
    rounded_class_values = np_module.round(class_values)
    if not bool(np_module.all(np_module.isfinite(class_values))):
        return False
    if not bool(
        np_module.all(np_module.abs(class_values - rounded_class_values) <= 1e-4)
    ):
        return False
    return bool(
        np_module.all(rounded_class_values >= 0)
        and np_module.all(rounded_class_values < int(num_classes))
    )


def _select_descending_topk_indices(
    *,
    np_module: Any,
    scores: Any,
    top_k: int,
) -> Any:
    """按分数从高到低选出 top-k 索引。"""

    if int(top_k) <= 0 or int(scores.shape[0]) <= 0:
        return np_module.asarray([], dtype=np_module.int64)
    return np_module.argsort(scores)[::-1][: int(top_k)].astype(
        np_module.int64,
        copy=False,
    )


def _validate_yolo26_detection_channel_count(
    *,
    channel_count: int,
    num_classes: int,
) -> None:
    """校验 YOLO26 detection 输出通道数。"""

    required_channel_count = 4 + int(num_classes)
    if int(channel_count) < required_channel_count:
        raise InvalidRequestError(
            "YOLO26 detection 推理输出通道数不足",
            details={
                "channel_count": int(channel_count),
                "required_channel_count": required_channel_count,
            },
        )


__all__ = [
    "DEFAULT_YOLO26_END2END_MAX_DETECTIONS",
    "YOLO26_DETECTION_POSTPROCESS_MODE_END2END_TOPK",
    "Yolo26DetectionTopKResult",
    "build_yolo26_detection_records",
    "is_yolo26_processed_class_id_column",
    "normalize_yolo26_detection_boxes_array",
    "normalize_yolo26_xyxy_box_order_array",
    "postprocess_yolo26_detection_prediction_array",
    "select_yolo26_end2end_topk_indices",
]
