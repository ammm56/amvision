"""YOLO 主线 segmentation NMS 前置后处理。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.decode import (
    decode_segmentation_masks,
)


@dataclass(frozen=True)
class SegmentationNmsInputArrays:
    """描述单张图片进入 NMS 前的 segmentation 候选结果。"""

    boxes_xyxy: Any
    scores: Any
    class_ids: Any
    mask_coefficients: Any


@dataclass(frozen=True)
class SegmentationPostprocessInstance:
    """描述 YOLO segmentation 后处理后的单个实例。"""

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None
    segments: tuple[tuple[tuple[float, float], ...], ...]
    mask_area: float


def normalize_segmentation_outputs(
    *,
    outputs: object,
    np_module: Any,
) -> tuple[Any, Any]:
    """把 segmentation 推理输出归一为 prediction/proto 两个数组。"""

    if not isinstance(outputs, list | tuple) or len(outputs) < 2:
        raise InvalidRequestError("segmentation 推理输出缺少 prediction/proto 双输出")
    prediction_array = np_module.asarray(outputs[0], dtype=np_module.float32)
    proto_array = np_module.asarray(outputs[1], dtype=np_module.float32)
    if prediction_array.ndim == 2:
        prediction_array = np_module.expand_dims(prediction_array, axis=0)
    if proto_array.ndim == 3:
        proto_array = np_module.expand_dims(proto_array, axis=0)
    if prediction_array.ndim < 3:
        raise InvalidRequestError(
            "segmentation prediction 输出维度不合法",
            details={"shape": list(prediction_array.shape)},
        )
    if proto_array.ndim != 4:
        raise InvalidRequestError(
            "segmentation proto 输出维度不合法",
            details={"shape": list(proto_array.shape)},
        )
    return prediction_array, proto_array


def build_segmentation_postprocess_instances(
    *,
    cv2_module: Any,
    np_module: Any,
    prediction_array: Any,
    proto_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    nms_threshold: float,
    mask_threshold: float,
    resize_ratio: float,
    image_width: int,
    image_height: int,
    input_size: tuple[int, int],
    nms_indices_func: Callable[..., Any],
) -> tuple[SegmentationPostprocessInstance, ...]:
    """把 segmentation 输出数组转换成通用实例记录。"""

    postprocess_results = postprocess_segmentation_prediction_array(
        prediction_array=prediction_array,
        np_module=np_module,
        num_classes=len(labels),
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        nms_indices_func=nms_indices_func,
    )
    if not postprocess_results:
        return ()
    prediction = postprocess_results[0]
    if prediction is None:
        return ()

    proto = proto_array[0]
    resized_height = min(int(round(image_height * resize_ratio)), int(input_size[0]))
    resized_width = min(int(round(image_width * resize_ratio)), int(input_size[1]))
    masks = decode_segmentation_masks(
        cv2_module=cv2_module,
        np_module=np_module,
        proto=proto,
        mask_coefficients=prediction.mask_coefficients,
        input_size=input_size,
        resized_width=resized_width,
        resized_height=resized_height,
        image_width=image_width,
        image_height=image_height,
        mask_threshold=mask_threshold,
    )

    instances: list[SegmentationPostprocessInstance] = []
    for bbox, score, class_id, binary_mask in zip(
        prediction.boxes_xyxy,
        prediction.scores,
        prediction.class_ids,
        masks,
        strict=True,
    ):
        scaled_bbox = bbox / max(resize_ratio, 1e-8)
        x1 = float(max(0.0, min(float(scaled_bbox[0]), float(image_width))))
        y1 = float(max(0.0, min(float(scaled_bbox[1]), float(image_height))))
        x2 = float(max(0.0, min(float(scaled_bbox[2]), float(image_width))))
        y2 = float(max(0.0, min(float(scaled_bbox[3]), float(image_height))))
        resolved_class_id = int(class_id)
        class_name = labels[resolved_class_id] if 0 <= resolved_class_id < len(labels) else None
        segments = extract_mask_segments(cv2_module=cv2_module, binary_mask=binary_mask)
        mask_area = float(np_module.count_nonzero(binary_mask))
        instances.append(
            SegmentationPostprocessInstance(
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


def prepare_segmentation_nms_inputs_array(
    *,
    image_prediction: Any,
    np_module: Any,
    num_classes: int,
    score_threshold: float,
) -> SegmentationNmsInputArrays | None:
    """从单张 segmentation 预测数组中筛出进入 NMS 的候选框和 mask coeff。"""

    _validate_segmentation_prediction_channel_count(
        channel_count=int(image_prediction.shape[1]),
        num_classes=num_classes,
    )
    boxes = image_prediction[:, :4]
    class_scores = image_prediction[:, 4 : 4 + num_classes]
    mask_coefficients = image_prediction[:, 4 + num_classes :]
    best_scores = np_module.max(class_scores, axis=1)
    best_class_ids = np_module.argmax(class_scores, axis=1).astype(np_module.int32, copy=False)
    keep_mask = best_scores >= score_threshold
    boxes = boxes[keep_mask]
    best_scores = best_scores[keep_mask]
    best_class_ids = best_class_ids[keep_mask]
    mask_coefficients = mask_coefficients[keep_mask]
    if int(boxes.shape[0]) <= 0:
        return None
    return SegmentationNmsInputArrays(
        boxes_xyxy=boxes,
        scores=best_scores,
        class_ids=best_class_ids,
        mask_coefficients=mask_coefficients,
    )


def postprocess_segmentation_prediction_array(
    *,
    prediction_array: Any,
    np_module: Any,
    num_classes: int,
    score_threshold: float,
    nms_threshold: float,
    nms_indices_func: Callable[..., Any],
) -> list[SegmentationNmsInputArrays | None]:
    """执行 segmentation 输出的阈值过滤与 NMS。"""

    normalized_prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    if normalized_prediction.ndim == 2:
        normalized_prediction = np_module.expand_dims(normalized_prediction, axis=0)
    if normalized_prediction.ndim < 3:
        raise InvalidRequestError(
            "segmentation 推理输出维度不合法",
            details={"shape": list(normalized_prediction.shape)},
        )
    _validate_segmentation_prediction_channel_count(
        channel_count=int(normalized_prediction.shape[2]),
        num_classes=num_classes,
    )

    results: list[SegmentationNmsInputArrays | None] = []
    for image_prediction in normalized_prediction:
        nms_inputs = prepare_segmentation_nms_inputs_array(
            image_prediction=image_prediction,
            np_module=np_module,
            num_classes=num_classes,
            score_threshold=score_threshold,
        )
        if nms_inputs is None:
            results.append(None)
            continue
        keep_indices = nms_indices_func(
            boxes=nms_inputs.boxes_xyxy,
            scores=nms_inputs.scores,
            class_ids=nms_inputs.class_ids,
            nms_threshold=nms_threshold,
            np_module=np_module,
        )
        if int(keep_indices.size) <= 0:
            results.append(None)
            continue
        results.append(
            SegmentationNmsInputArrays(
                boxes_xyxy=nms_inputs.boxes_xyxy[keep_indices],
                scores=nms_inputs.scores[keep_indices],
                class_ids=nms_inputs.class_ids[keep_indices],
                mask_coefficients=nms_inputs.mask_coefficients[keep_indices],
            )
        )
    return results


def extract_mask_segments(
    *,
    cv2_module: Any,
    binary_mask: Any,
) -> tuple[tuple[tuple[float, float], ...], ...]:
    """从二值 mask 中提取多边形轮廓。"""

    contours, _hierarchy = cv2_module.findContours(
        binary_mask,
        cv2_module.RETR_EXTERNAL,
        cv2_module.CHAIN_APPROX_SIMPLE,
    )
    segments: list[tuple[tuple[float, float], ...]] = []
    for contour in contours:
        if contour is None or len(contour) < 3:
            continue
        flattened = contour.reshape(-1, 2)
        segments.append(
            tuple((round(float(point[0]), 3), round(float(point[1]), 3)) for point in flattened)
        )
    return tuple(segments)


def _validate_segmentation_prediction_channel_count(
    *,
    channel_count: int,
    num_classes: int,
) -> None:
    """校验 segmentation 预测通道数是否包含 box、类别分数和 mask coeff。"""

    required_min_channels = 5 + int(num_classes)
    if int(channel_count) < required_min_channels:
        raise InvalidRequestError(
            "segmentation 推理输出通道数不足",
            details={
                "channel_count": int(channel_count),
                "required_min_channels": required_min_channels,
            },
        )
