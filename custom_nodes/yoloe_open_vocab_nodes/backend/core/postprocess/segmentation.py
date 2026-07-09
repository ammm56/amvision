"""YOLOE segmentation runtime 输出后处理。"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image

from backend.service.application.errors import InvalidRequestError
from backend.service.application.images import decode_image_bytes_to_matrix
from backend.service.application.runtime.support.detection import batched_nms_indices


def decode_runtime_image(cv2_module: Any, np_module: Any, image_bytes: bytes, image_payload: object) -> Any:
    """把节点输入图片字节解码成 OpenCV BGR 图像。"""

    return decode_image_bytes_to_matrix(
        cv2_module=cv2_module,
        np_module=np_module,
        image_bytes=image_bytes,
        image_payload=image_payload,
        imdecode_flags=cv2_module.IMREAD_COLOR,
        error_message="YOLOE prompt-free 节点收到的图片不是有效图像",
        copy_raw=True,
    )


def postprocess_prompt_free_outputs(
    *,
    cv2_module: Any,
    np_module: Any,
    prediction_array: Any,
    proto_array: Any,
    class_names: dict[int, str],
    confidence_threshold: float,
    iou_threshold: float,
    max_detections: int,
    resize_ratio: float,
    image_width: int,
    image_height: int,
    input_size: tuple[int, int],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """把 YOLOE segmentation head 输出转换为 detections 和 regions。"""

    normalized_prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    normalized_proto = np_module.asarray(proto_array, dtype=np_module.float32)
    if normalized_prediction.ndim == 2:
        normalized_prediction = np_module.expand_dims(normalized_prediction, axis=0)
    if normalized_proto.ndim == 3:
        normalized_proto = np_module.expand_dims(normalized_proto, axis=0)
    if normalized_prediction.ndim != 3 or normalized_prediction.shape[0] != 1:
        raise InvalidRequestError(
            "YOLOE prompt-free 推理输出维度不合法",
            details={"prediction_shape": list(normalized_prediction.shape)},
        )
    if normalized_proto.ndim != 4 or normalized_proto.shape[0] != 1:
        raise InvalidRequestError(
            "YOLOE prompt-free proto 输出维度不合法",
            details={"proto_shape": list(normalized_proto.shape)},
        )
    num_classes = len(class_names)
    if int(normalized_prediction.shape[2]) <= 4 + num_classes:
        raise InvalidRequestError(
            "YOLOE prompt-free 推理输出通道数不足",
            details={
                "channel_count": int(normalized_prediction.shape[2]),
                "required_min_channels": 5 + num_classes,
            },
        )

    image_prediction = normalized_prediction[0]
    boxes = image_prediction[:, :4]
    class_scores = image_prediction[:, 4 : 4 + num_classes]
    mask_coefficients = image_prediction[:, 4 + num_classes :]
    if int(boxes.shape[0]) <= 0:
        return [], []

    best_scores = np_module.max(class_scores, axis=1)
    best_class_ids = np_module.argmax(class_scores, axis=1).astype(np_module.int32, copy=False)
    keep_mask = best_scores >= float(confidence_threshold)
    boxes = boxes[keep_mask]
    best_scores = best_scores[keep_mask]
    best_class_ids = best_class_ids[keep_mask]
    mask_coefficients = mask_coefficients[keep_mask]
    if int(boxes.shape[0]) <= 0:
        return [], []

    keep_indices = batched_nms_indices(
        boxes=boxes,
        scores=best_scores,
        class_ids=best_class_ids,
        nms_threshold=float(iou_threshold),
        np_module=np_module,
    )
    if int(keep_indices.size) <= 0:
        return [], []

    keep_indices = keep_indices[: int(max_detections)]
    boxes = boxes[keep_indices]
    best_scores = best_scores[keep_indices]
    best_class_ids = best_class_ids[keep_indices]
    mask_coefficients = mask_coefficients[keep_indices]

    resized_height = min(int(round(image_height * resize_ratio)), int(input_size[0]))
    resized_width = min(int(round(image_width * resize_ratio)), int(input_size[1]))
    proto = normalized_proto[0]
    masks = _decode_segmentation_masks(
        cv2_module=cv2_module,
        np_module=np_module,
        proto=proto,
        mask_coefficients=mask_coefficients,
        input_size=input_size,
        resized_width=resized_width,
        resized_height=resized_height,
        image_width=image_width,
        image_height=image_height,
    )

    detections: list[dict[str, object]] = []
    regions: list[dict[str, object]] = []
    for index, (bbox, score, class_id, binary_mask) in enumerate(
        zip(boxes, best_scores, best_class_ids, masks, strict=True),
        start=1,
    ):
        scaled_bbox = bbox / max(resize_ratio, 1e-8)
        x1 = float(max(0.0, min(float(scaled_bbox[0]), float(image_width))))
        y1 = float(max(0.0, min(float(scaled_bbox[1]), float(image_height))))
        x2 = float(max(0.0, min(float(scaled_bbox[2]), float(image_width))))
        y2 = float(max(0.0, min(float(scaled_bbox[3]), float(image_height))))
        class_index = int(class_id)
        class_name = class_names.get(class_index, str(class_index))
        bbox_xyxy = [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]
        detections.append(
            {
                "bbox_xyxy": bbox_xyxy,
                "score": round(float(score), 6),
                "class_id": class_index,
                "class_name": class_name,
            }
        )
        polygon_xy = _extract_primary_polygon(
            cv2_module=cv2_module,
            binary_mask=binary_mask,
            fallback_bbox_xyxy=bbox_xyxy,
        )
        mask_png_bytes, mask_width, mask_height, mask_area = _encode_binary_mask_png(binary_mask)
        region_item = {
            "region_id": f"region-{index}",
            "bbox_xyxy": bbox_xyxy,
            "score": round(float(score), 6),
            "class_id": class_index,
            "class_name": class_name,
            "polygon_xy": polygon_xy,
            "area": int(mask_area),
        }
        if mask_png_bytes is not None and mask_width is not None and mask_height is not None:
            region_item["mask_png_bytes"] = mask_png_bytes
            region_item["mask_width"] = mask_width
            region_item["mask_height"] = mask_height
        regions.append(region_item)
    return detections, regions


def _decode_segmentation_masks(
    *,
    cv2_module: Any,
    np_module: Any,
    proto: Any,
    mask_coefficients: Any,
    input_size: tuple[int, int],
    resized_width: int,
    resized_height: int,
    image_width: int,
    image_height: int,
    mask_threshold: float = 0.5,
) -> list[Any]:
    """按 YOLOE proto 和 mask 系数还原原图尺寸二值 mask。"""

    proto_features = proto.reshape(int(proto.shape[0]), -1)
    mask_logits = mask_coefficients @ proto_features
    mask_logits = mask_logits.reshape(int(mask_coefficients.shape[0]), int(proto.shape[1]), int(proto.shape[2]))
    masks: list[Any] = []
    for mask_logit in mask_logits:
        clipped_mask_logit = np_module.clip(mask_logit, -50.0, 50.0)
        probability_mask = 1.0 / (1.0 + np_module.exp(-clipped_mask_logit))
        resized_mask = cv2_module.resize(
            probability_mask,
            (int(input_size[1]), int(input_size[0])),
            interpolation=cv2_module.INTER_LINEAR,
        )
        cropped_mask = resized_mask[:resized_height, :resized_width]
        restored_mask = cv2_module.resize(
            cropped_mask,
            (int(image_width), int(image_height)),
            interpolation=cv2_module.INTER_LINEAR,
        )
        binary_mask = (restored_mask >= float(mask_threshold)).astype(np_module.uint8)
        masks.append(binary_mask)
    return masks


def _extract_primary_polygon(*, cv2_module: Any, binary_mask: Any, fallback_bbox_xyxy: list[float]) -> list[list[float]]:
    """从 mask 最大外轮廓提取 polygon，失败时回退到 bbox 四边形。"""

    contours, _hierarchy = cv2_module.findContours(
        binary_mask,
        cv2_module.RETR_EXTERNAL,
        cv2_module.CHAIN_APPROX_SIMPLE,
    )
    best_polygon: list[list[float]] | None = None
    best_area = -1.0
    for contour in contours:
        if contour is None or len(contour) < 3:
            continue
        flattened = contour.reshape(-1, 2)
        area = float(cv2_module.contourArea(flattened))
        if area <= best_area:
            continue
        best_area = area
        best_polygon = [[round(float(point[0]), 3), round(float(point[1]), 3)] for point in flattened]
    if best_polygon:
        return best_polygon
    x1_value, y1_value, x2_value, y2_value = fallback_bbox_xyxy
    return [
        [float(x1_value), float(y1_value)],
        [float(x2_value), float(y1_value)],
        [float(x2_value), float(y2_value)],
        [float(x1_value), float(y2_value)],
    ]


def _encode_binary_mask_png(binary_mask: Any) -> tuple[bytes | None, int | None, int | None, int]:
    """把二值 mask 编码成 PNG bytes，供 regions payload 保存。"""

    normalized_mask = np.asarray(binary_mask, dtype=np.uint8)
    if normalized_mask.ndim != 2:
        return None, None, None, 0
    encoded_mask = normalized_mask * 255
    mask_height, mask_width = encoded_mask.shape
    mask_area = int(np.count_nonzero(normalized_mask))
    encoded_image = Image.fromarray(encoded_mask, mode="L")
    buffer = io.BytesIO()
    encoded_image.save(buffer, format="PNG")
    return buffer.getvalue(), int(mask_width), int(mask_height), mask_area


__all__ = [
    "decode_runtime_image",
    "postprocess_prompt_free_outputs",
]
