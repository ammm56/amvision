"""YOLOX detection 推理后处理。"""

from __future__ import annotations

from typing import Any, Callable

from backend.service.application.errors import InvalidRequestError


def ensure_yolox_prediction_array(*, prediction_value: Any, np_module: Any, backend_name: str) -> Any:
    """把后端原始输出规范化为 batch x boxes x channels 的预测数组。"""

    prediction_array = np_module.asarray(prediction_value, dtype=np_module.float32)
    if prediction_array.ndim == 2:
        prediction_array = np_module.expand_dims(prediction_array, axis=0)
    if prediction_array.ndim < 3:
        raise InvalidRequestError(
            f"{backend_name} 推理输出维度不合法",
            details={"shape": list(prediction_array.shape)},
        )
    return prediction_array


def postprocess_yolox_prediction_array(
    *,
    prediction_array: Any,
    np_module: Any,
    num_classes: int,
    conf_thre: float,
    nms_thre: float,
) -> list[Any]:
    """使用 NumPy 版本 YOLOX 后处理把原始输出转换为候选检测框。"""

    if int(prediction_array.shape[2]) < 5 + num_classes:
        raise InvalidRequestError(
            "推理输出通道数不足，无法执行 YOLOX 后处理",
            details={
                "channel_count": int(prediction_array.shape[2]),
                "required_channel_count": 5 + num_classes,
            },
        )
    working_prediction = np_module.asarray(prediction_array, dtype=np_module.float32).copy()
    working_prediction[:, :, 0] = prediction_array[:, :, 0] - prediction_array[:, :, 2] / 2
    working_prediction[:, :, 1] = prediction_array[:, :, 1] - prediction_array[:, :, 3] / 2
    working_prediction[:, :, 2] = prediction_array[:, :, 0] + prediction_array[:, :, 2] / 2
    working_prediction[:, :, 3] = prediction_array[:, :, 1] + prediction_array[:, :, 3] / 2

    output: list[Any] = [None for _ in range(len(working_prediction))]
    for index, image_prediction in enumerate(working_prediction):
        if int(image_prediction.shape[0]) <= 0:
            continue
        class_scores = image_prediction[:, 5 : 5 + num_classes]
        class_conf = np_module.max(class_scores, axis=1)
        class_pred = np_module.argmax(class_scores, axis=1).astype(np_module.float32, copy=False)
        combined_scores = image_prediction[:, 4] * class_conf
        conf_mask = combined_scores >= conf_thre
        detections = np_module.concatenate(
            (
                image_prediction[:, :5],
                class_conf[:, None],
                class_pred[:, None],
            ),
            axis=1,
        )
        detections = detections[conf_mask]
        combined_scores = combined_scores[conf_mask]
        if int(detections.shape[0]) <= 0:
            continue
        keep_indices = batched_yolox_nms_indices(
            boxes=detections[:, :4],
            scores=combined_scores,
            class_ids=detections[:, 6].astype(np_module.int32, copy=False),
            nms_threshold=nms_thre,
            np_module=np_module,
        )
        if int(keep_indices.size) <= 0:
            continue
        output[index] = detections[keep_indices]
    return output


def build_yolox_detection_records(
    *,
    np_module: Any,
    predictions: Any,
    resize_ratio: float,
    labels: tuple[str, ...],
    image_width: int,
    image_height: int,
    detection_factory: Callable[..., Any],
) -> tuple[Any, ...]:
    """把 YOLOX postprocess 输出归一成 detection 记录。"""

    if not isinstance(predictions, list) or not predictions:
        return ()
    prediction_tensor = predictions[0]
    if prediction_tensor is None:
        return ()

    prediction_array = yolox_prediction_to_numpy_array(
        prediction_tensor=prediction_tensor,
        np_module=np_module,
    )
    detections: list[Any] = []
    for prediction in prediction_array:
        if len(prediction) < 7:
            continue
        bbox = prediction[:4] / max(resize_ratio, 1e-8)
        x1 = float(max(0.0, min(float(bbox[0]), float(image_width))))
        y1 = float(max(0.0, min(float(bbox[1]), float(image_height))))
        x2 = float(max(0.0, min(float(bbox[2]), float(image_width))))
        y2 = float(max(0.0, min(float(bbox[3]), float(image_height))))
        class_id = int(prediction[6])
        class_name = labels[class_id] if 0 <= class_id < len(labels) else None
        score = float(prediction[4] * prediction[5])
        detections.append(
            detection_factory(
                bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)),
                score=round(score, 6),
                class_id=class_id,
                class_name=class_name,
            )
        )

    detections.sort(key=lambda item: item.score, reverse=True)
    return tuple(detections)


def yolox_prediction_to_numpy_array(*, prediction_tensor: Any, np_module: Any) -> Any:
    """把 Tensor 或数组候选结果统一转换为 NumPy 数组。"""

    normalized_value = prediction_tensor
    if hasattr(normalized_value, "detach"):
        normalized_value = normalized_value.detach()
    if hasattr(normalized_value, "cpu"):
        normalized_value = normalized_value.cpu()
    if hasattr(normalized_value, "numpy"):
        normalized_value = normalized_value.numpy()
    return np_module.asarray(normalized_value, dtype=np_module.float32)


def batched_yolox_nms_indices(
    *,
    boxes: Any,
    scores: Any,
    class_ids: Any,
    nms_threshold: float,
    np_module: Any,
) -> Any:
    """按类别执行 batched NMS 并返回保留索引。"""

    if int(boxes.shape[0]) <= 0:
        return np_module.asarray([], dtype=np_module.int64)

    keep_indices: list[int] = []
    for class_id in np_module.unique(class_ids):
        class_mask = class_ids == class_id
        candidate_indices = np_module.flatnonzero(class_mask)
        class_keep = yolox_nms_indices(
            boxes=boxes[class_mask],
            scores=scores[class_mask],
            nms_threshold=nms_threshold,
            np_module=np_module,
        )
        keep_indices.extend(int(candidate_indices[index]) for index in class_keep.tolist())
    keep_indices.sort(key=lambda index: float(scores[index]), reverse=True)
    return np_module.asarray(keep_indices, dtype=np_module.int64)


def yolox_nms_indices(*, boxes: Any, scores: Any, nms_threshold: float, np_module: Any) -> Any:
    """对单个类别的候选框执行标准 NMS。"""

    if int(boxes.shape[0]) <= 0:
        return np_module.asarray([], dtype=np_module.int64)
    order = np_module.argsort(scores)[::-1]
    keep_indices: list[int] = []
    while int(order.size) > 0:
        current_index = int(order[0])
        keep_indices.append(current_index)
        if int(order.size) == 1:
            break
        remaining_order = order[1:]
        iou_values = compute_yolox_iou_array(
            box=boxes[current_index],
            boxes=boxes[remaining_order],
            np_module=np_module,
        )
        order = remaining_order[iou_values <= nms_threshold]
    return np_module.asarray(keep_indices, dtype=np_module.int64)


def compute_yolox_iou_array(*, box: Any, boxes: Any, np_module: Any) -> Any:
    """计算单个边界框与一组边界框的 IoU。"""

    x1 = np_module.maximum(box[0], boxes[:, 0])
    y1 = np_module.maximum(box[1], boxes[:, 1])
    x2 = np_module.minimum(box[2], boxes[:, 2])
    y2 = np_module.minimum(box[3], boxes[:, 3])
    intersection_width = np_module.maximum(0.0, x2 - x1)
    intersection_height = np_module.maximum(0.0, y2 - y1)
    intersection_area = intersection_width * intersection_height

    box_area = np_module.maximum(0.0, box[2] - box[0]) * np_module.maximum(0.0, box[3] - box[1])
    boxes_area = np_module.maximum(0.0, boxes[:, 2] - boxes[:, 0]) * np_module.maximum(
        0.0,
        boxes[:, 3] - boxes[:, 1],
    )
    union_area = np_module.maximum(box_area + boxes_area - intersection_area, 1e-12)
    return intersection_area / union_area
