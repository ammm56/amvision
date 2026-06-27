"""YOLO26 segmentation 后处理入口。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo26_core.postprocess.detection import (
    DEFAULT_YOLO26_END2END_MAX_DETECTIONS,
    is_yolo26_processed_class_id_column,
    normalize_yolo26_detection_boxes_array,
    select_yolo26_end2end_topk_indices,
)
from backend.service.application.models.yolo_core_common.geometry import (
    YoloLetterboxTransform,
    scale_yolo_box_from_letterbox,
)


@dataclass(frozen=True)
class Yolo26SegmentationTopKInputArrays:
    """描述单张图片 YOLO26 segmentation top-k 候选结果。"""

    boxes_xyxy: Any
    scores: Any
    class_ids: Any
    mask_coefficients: Any


@dataclass(frozen=True)
class Yolo26SegmentationPostprocessInstance:
    """描述 YOLO26 segmentation 后处理后的单个实例。"""

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None
    segments: tuple[tuple[tuple[float, float], ...], ...]
    mask_area: float


SegmentationTopKInputArrays = Yolo26SegmentationTopKInputArrays
SegmentationPostprocessInstance = Yolo26SegmentationPostprocessInstance


def normalize_yolo26_segmentation_outputs(
    *,
    outputs: object,
    np_module: Any,
    num_classes: int,
) -> tuple[Any, Any]:
    """归一化 YOLO26 segmentation 的 prediction / proto 输出。"""

    if not isinstance(outputs, list | tuple) or len(outputs) < 2:
        raise InvalidRequestError(
            "YOLO26 segmentation 推理输出缺少 prediction/proto 双输出"
        )
    prediction_array = np_module.asarray(outputs[0], dtype=np_module.float32)
    proto_array = np_module.asarray(outputs[1], dtype=np_module.float32)
    if prediction_array.ndim == 2:
        prediction_array = np_module.expand_dims(prediction_array, axis=0)
    if proto_array.ndim == 3:
        proto_array = np_module.expand_dims(proto_array, axis=0)
    if prediction_array.ndim < 3:
        raise InvalidRequestError(
            "YOLO26 segmentation prediction 输出维度不合法",
            details={"shape": list(prediction_array.shape)},
        )
    if _is_yolo26_channel_first_prediction(
        prediction_array=prediction_array,
        num_classes=num_classes,
    ):
        prediction_array = np_module.transpose(prediction_array, (0, 2, 1))
    if proto_array.ndim != 4:
        raise InvalidRequestError(
            "YOLO26 segmentation proto 输出维度不合法",
            details={"shape": list(proto_array.shape)},
        )
    return prediction_array, proto_array


def build_yolo26_segmentation_postprocess_instances(
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
    """把 YOLO26 segmentation 输出转换为实例记录。"""

    proto = proto_array[0]
    mask_coefficient_count = int(proto.shape[0])
    postprocess_results = postprocess_yolo26_segmentation_prediction_array(
        prediction_array=prediction_array,
        np_module=np_module,
        num_classes=len(labels),
        mask_coefficient_count=mask_coefficient_count,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        nms_indices_func=nms_indices_func,
    )
    if not postprocess_results:
        return ()
    prediction = postprocess_results[0]
    if prediction is None:
        return ()

    masks = decode_yolo26_segmentation_masks(
        cv2_module=cv2_module,
        np_module=np_module,
        proto=proto,
        mask_coefficients=prediction.mask_coefficients,
        letterbox_transform=letterbox_transform,
        mask_threshold=mask_threshold,
    )

    instances: list[Yolo26SegmentationPostprocessInstance] = []
    for bbox, score, class_id, binary_mask in zip(
        prediction.boxes_xyxy,
        prediction.scores,
        prediction.class_ids,
        masks,
        strict=True,
    ):
        scaled_bbox = scale_yolo_box_from_letterbox(
            box_xyxy=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
            transform=letterbox_transform,
        )
        if scaled_bbox is None:
            continue
        x1, y1, x2, y2 = scaled_bbox
        resolved_class_id = int(class_id)
        class_name = (
            labels[resolved_class_id] if 0 <= resolved_class_id < len(labels) else None
        )
        segments = extract_yolo26_mask_segments(
            cv2_module=cv2_module, binary_mask=binary_mask
        )
        mask_area = float(np_module.count_nonzero(binary_mask))
        if mask_area <= 0.0 or not segments:
            continue
        instances.append(
            Yolo26SegmentationPostprocessInstance(
                bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)),
                score=round(float(score), 6),
                class_id=resolved_class_id,
                class_name=class_name,
                segments=segments,
                mask_area=round(mask_area, 3),
            )
        )
    instances.sort(key=lambda item: item.score, reverse=True)
    return tuple(instances)


def prepare_yolo26_segmentation_topk_inputs_array(
    *,
    image_prediction: Any,
    np_module: Any,
    num_classes: int,
    score_threshold: float,
) -> Yolo26SegmentationTopKInputArrays | None:
    """筛选 YOLO26 segmentation 候选。"""

    _validate_yolo26_segmentation_prediction_channel_count(
        channel_count=int(image_prediction.shape[1]),
        num_classes=num_classes,
    )
    boxes = image_prediction[:, :4]
    class_scores = image_prediction[:, 4 : 4 + num_classes]
    mask_coefficients = image_prediction[:, 4 + num_classes :]
    best_scores = np_module.max(class_scores, axis=1)
    best_class_ids = np_module.argmax(class_scores, axis=1).astype(
        np_module.int32, copy=False
    )
    keep_mask = best_scores >= score_threshold
    boxes = boxes[keep_mask]
    best_scores = best_scores[keep_mask]
    best_class_ids = best_class_ids[keep_mask]
    mask_coefficients = mask_coefficients[keep_mask]
    if int(boxes.shape[0]) <= 0:
        return None
    return Yolo26SegmentationTopKInputArrays(
        boxes_xyxy=boxes,
        scores=best_scores,
        class_ids=best_class_ids,
        mask_coefficients=mask_coefficients,
    )


def postprocess_yolo26_segmentation_prediction_array(
    *,
    prediction_array: Any,
    np_module: Any,
    num_classes: int,
    mask_coefficient_count: int,
    score_threshold: float,
    nms_threshold: float,
    nms_indices_func: Callable[..., Any],
) -> list[Yolo26SegmentationTopKInputArrays | None]:
    """执行 YOLO26 segmentation end2end top-k 后处理。"""

    _ = nms_threshold, nms_indices_func
    normalized_prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    if normalized_prediction.ndim == 2:
        normalized_prediction = np_module.expand_dims(normalized_prediction, axis=0)
    if normalized_prediction.ndim < 3:
        raise InvalidRequestError(
            "YOLO26 segmentation 推理输出维度不合法",
            details={"shape": list(normalized_prediction.shape)},
        )
    if _is_yolo26_channel_first_prediction(
        prediction_array=normalized_prediction,
        num_classes=num_classes,
    ):
        normalized_prediction = np_module.transpose(normalized_prediction, (0, 2, 1))
    processed_results = _postprocess_yolo26_segmentation_processed_array(
        prediction_array=normalized_prediction,
        np_module=np_module,
        num_classes=num_classes,
        mask_coefficient_count=mask_coefficient_count,
        score_threshold=score_threshold,
    )
    if processed_results is not None:
        return processed_results
    _validate_yolo26_segmentation_prediction_channel_count(
        channel_count=int(normalized_prediction.shape[2]),
        num_classes=num_classes,
    )

    results: list[Yolo26SegmentationTopKInputArrays | None] = []
    for image_prediction in normalized_prediction:
        class_scores = image_prediction[:, 4 : 4 + int(num_classes)]
        selected_scores, selected_class_ids, selected_anchor_indices = (
            select_yolo26_end2end_topk_indices(
                np_module=np_module,
                class_scores=class_scores,
                max_detections=DEFAULT_YOLO26_END2END_MAX_DETECTIONS,
            )
        )
        if int(selected_anchor_indices.size) <= 0:
            results.append(None)
            continue
        keep_mask = selected_scores >= float(score_threshold)
        if not bool(np_module.any(keep_mask)):
            results.append(None)
            continue
        selected_anchor_indices = selected_anchor_indices[keep_mask]
        boxes = normalize_yolo26_detection_boxes_array(
            boxes=image_prediction[selected_anchor_indices, :4],
            np_module=np_module,
            box_format="xyxy",
        )
        mask_start_index = 4 + int(num_classes)
        results.append(
            Yolo26SegmentationTopKInputArrays(
                boxes_xyxy=boxes,
                scores=selected_scores[keep_mask],
                class_ids=selected_class_ids[keep_mask],
                mask_coefficients=image_prediction[
                    selected_anchor_indices,
                    mask_start_index:,
                ],
            )
        )
    return results


def _postprocess_yolo26_segmentation_processed_array(
    *,
    prediction_array: Any,
    np_module: Any,
    num_classes: int,
    mask_coefficient_count: int,
    score_threshold: float,
) -> list[Yolo26SegmentationTopKInputArrays | None] | None:
    """解析官方 YOLO26 export processed segmentation 输出。"""

    if int(prediction_array.shape[1]) > DEFAULT_YOLO26_END2END_MAX_DETECTIONS:
        return None
    if int(prediction_array.shape[2]) != 6 + int(mask_coefficient_count):
        return None
    if not is_yolo26_processed_class_id_column(
        np_module=np_module,
        prediction_array=prediction_array,
        class_column_index=5,
        num_classes=num_classes,
    ):
        return None

    results: list[Yolo26SegmentationTopKInputArrays | None] = []
    for image_prediction in prediction_array:
        scores = image_prediction[:, 4]
        keep_mask = scores >= float(score_threshold)
        if not bool(np_module.any(keep_mask)):
            results.append(None)
            continue
        results.append(
            Yolo26SegmentationTopKInputArrays(
                boxes_xyxy=normalize_yolo26_detection_boxes_array(
                    boxes=image_prediction[keep_mask, :4],
                    np_module=np_module,
                    box_format="xyxy",
                ),
                scores=scores[keep_mask],
                class_ids=image_prediction[keep_mask, 5].astype(
                    np_module.int32,
                    copy=False,
                ),
                mask_coefficients=image_prediction[
                    keep_mask,
                    6 : 6 + int(mask_coefficient_count),
                ],
            )
        )
    return results


def decode_yolo26_segmentation_masks(
    *,
    cv2_module: Any,
    np_module: Any,
    proto: Any,
    mask_coefficients: Any,
    letterbox_transform: YoloLetterboxTransform,
    mask_threshold: float,
) -> list[Any]:
    """根据 YOLO26 proto 与 mask coeff 解码实例 mask。"""

    proto_features = proto.reshape(int(proto.shape[0]), -1)
    mask_logits = mask_coefficients @ proto_features
    mask_logits = mask_logits.reshape(
        int(mask_coefficients.shape[0]),
        int(proto.shape[1]),
        int(proto.shape[2]),
    )
    masks: list[Any] = []
    for mask_logit in mask_logits:
        mask_logit = np_module.clip(mask_logit, -60.0, 60.0)
        probability_mask = 1.0 / (1.0 + np_module.exp(-mask_logit))
        resized_mask = cv2_module.resize(
            probability_mask,
            (letterbox_transform.target_width, letterbox_transform.target_height),
            interpolation=cv2_module.INTER_LINEAR,
        )
        crop_top = letterbox_transform.pad_top
        crop_left = letterbox_transform.pad_left
        crop_bottom = min(
            letterbox_transform.target_height,
            crop_top + letterbox_transform.resized_height,
        )
        crop_right = min(
            letterbox_transform.target_width,
            crop_left + letterbox_transform.resized_width,
        )
        cropped_mask = resized_mask[crop_top:crop_bottom, crop_left:crop_right]
        restored_mask = cv2_module.resize(
            cropped_mask,
            (letterbox_transform.source_width, letterbox_transform.source_height),
            interpolation=cv2_module.INTER_LINEAR,
        )
        binary_mask = (restored_mask >= mask_threshold).astype(np_module.uint8)
        masks.append(binary_mask)
    return masks


def extract_yolo26_mask_segments(
    *,
    cv2_module: Any,
    binary_mask: Any,
) -> tuple[tuple[tuple[float, float], ...], ...]:
    """从 YOLO26 binary mask 中提取多边形轮廓。"""

    contours, _hierarchy = cv2_module.findContours(
        binary_mask,
        cv2_module.RETR_EXTERNAL,
        cv2_module.CHAIN_APPROX_SIMPLE,
    )
    segments: list[tuple[tuple[float, float], ...]] = []
    for contour in contours:
        if contour is None or len(contour) < 3:
            continue
        if float(cv2_module.contourArea(contour)) <= 0.0:
            continue
        flattened = contour.reshape(-1, 2)
        segments.append(
            tuple(
                (round(float(point[0]), 3), round(float(point[1]), 3))
                for point in flattened
            )
        )
    return tuple(segments)


def _validate_yolo26_segmentation_prediction_channel_count(
    *,
    channel_count: int,
    num_classes: int,
) -> None:
    """校验 YOLO26 segmentation 预测通道数是否包含 box、类别分数和 mask coeff。"""

    required_min_channels = 5 + int(num_classes)
    if int(channel_count) < required_min_channels:
        raise InvalidRequestError(
            "YOLO26 segmentation 推理输出通道数不足",
            details={
                "channel_count": int(channel_count),
                "required_min_channels": required_min_channels,
            },
        )


def _is_yolo26_channel_first_prediction(
    *,
    prediction_array: Any,
    num_classes: int,
) -> bool:
    """判断 prediction 是否为 Ultralytics export 的 [B, C, N] 布局。"""

    if getattr(prediction_array, "ndim", 0) != 3:
        return False
    required_min_channels = 5 + int(num_classes)
    return int(prediction_array.shape[1]) >= required_min_channels and int(
        prediction_array.shape[2]
    ) > int(prediction_array.shape[1])


__all__ = [
    "SegmentationTopKInputArrays",
    "SegmentationPostprocessInstance",
    "Yolo26SegmentationTopKInputArrays",
    "Yolo26SegmentationPostprocessInstance",
    "build_yolo26_segmentation_postprocess_instances",
    "decode_yolo26_segmentation_masks",
    "extract_yolo26_mask_segments",
    "normalize_yolo26_segmentation_outputs",
    "postprocess_yolo26_segmentation_prediction_array",
    "prepare_yolo26_segmentation_topk_inputs_array",
]
