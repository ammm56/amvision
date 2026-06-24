"""YOLOE 节点输出 payload 构造。"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image
import torch

from backend.nodes.runtime_support import register_image_bytes
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.yoloe_open_vocab_nodes.backend.payloads.types import (
    YoloeDetectionPrediction,
    YoloePretrainedVariant,
    YoloePromptItem,
    YoloeVisualPromptItem,
)


def build_predict_kwargs(
    *,
    source_image: Image.Image,
    device: str,
    precision: str,
    confidence_threshold: float,
    iou_threshold: float,
    max_detections: int,
) -> dict[str, object]:
    """构造统一的 YOLOE 推理参数。"""

    return {
        "source": source_image,
        "device": device,
        "verbose": False,
        "conf": confidence_threshold,
        "iou": iou_threshold,
        "max_det": max_detections,
        "half": precision == "fp16",
    }


def build_detection_items_from_runtime_result(
    result: object,
    *,
    class_name_map: dict[int, str] | None = None,
    prompt_id_map: dict[int, str] | None = None,
    source_text_map: dict[int, str] | None = None,
) -> list[dict[str, object]]:
    """把 YOLOE 运行时结果规整为 detections.v1 items。"""

    if result is None or getattr(result, "boxes", None) is None:
        return []
    result_names = getattr(result, "names", None)
    detection_items: list[dict[str, object]] = []
    boxes = result.boxes
    for index in range(len(boxes)):
        box = boxes[index]
        class_id = int(box.cls[0].item())
        score = float(box.conf[0].item())
        bbox_xyxy = [float(value) for value in box.xyxy[0].tolist()]
        class_name = (
            (class_name_map or {}).get(class_id)
            or (source_text_map or {}).get(class_id)
            or read_runtime_result_class_name(result_names, class_id)
            or str(class_id)
        )
        item = {
            "bbox_xyxy": bbox_xyxy,
            "score": score,
            "class_id": class_id,
            "class_name": class_name,
        }
        prompt_id = (prompt_id_map or {}).get(class_id)
        if prompt_id is not None:
            item["prompt_id"] = prompt_id
        source_prompt_text = (source_text_map or {}).get(class_id)
        if source_prompt_text is not None:
            item["source_prompt_text"] = source_prompt_text
        detection_items.append(item)
    return detection_items


def build_region_items_from_runtime_result(
    result: object,
    *,
    class_name_map: dict[int, str] | None = None,
    prompt_id_map: dict[int, str] | None = None,
    source_text_map: dict[int, str] | None = None,
) -> list[dict[str, object]]:
    """把 YOLOE 运行时结果规整为 regions.v1 items。"""

    if result is None or getattr(result, "boxes", None) is None:
        return []

    result_names = getattr(result, "names", None)
    boxes = result.boxes
    masks = getattr(result, "masks", None)
    polygon_items = getattr(masks, "xy", None) if masks is not None else None
    mask_tensor_items = getattr(masks, "data", None) if masks is not None else None
    region_items: list[dict[str, object]] = []

    for index in range(len(boxes)):
        box = boxes[index]
        class_id = int(box.cls[0].item())
        score = float(box.conf[0].item())
        bbox_xyxy = [float(value) for value in box.xyxy[0].tolist()]
        class_name = (
            (class_name_map or {}).get(class_id)
            or (source_text_map or {}).get(class_id)
            or read_runtime_result_class_name(result_names, class_id)
            or str(class_id)
        )
        polygon_xy = normalize_runtime_polygon_xy(
            polygon_items[index] if isinstance(polygon_items, (list, tuple)) and index < len(polygon_items) else None,
            fallback_bbox_xyxy=bbox_xyxy,
        )
        mask_tensor = None
        if torch.is_tensor(mask_tensor_items) and index < int(mask_tensor_items.shape[0]):
            mask_tensor = mask_tensor_items[index]
        mask_png_bytes, mask_width, mask_height, mask_area = encode_runtime_mask_png(mask_tensor)
        item = {
            "region_id": f"region-{index + 1}",
            "bbox_xyxy": bbox_xyxy,
            "score": score,
            "class_id": class_id,
            "class_name": class_name,
            "polygon_xy": polygon_xy,
            "area": mask_area,
        }
        prompt_id = (prompt_id_map or {}).get(class_id)
        if prompt_id is not None:
            item["prompt_id"] = prompt_id
        source_prompt_text = (source_text_map or {}).get(class_id)
        if source_prompt_text is not None:
            item["source_prompt_text"] = source_prompt_text
        if mask_png_bytes is not None and mask_width is not None and mask_height is not None:
            item["mask_png_bytes"] = mask_png_bytes
            item["mask_width"] = mask_width
            item["mask_height"] = mask_height
        region_items.append(item)
    return region_items


def read_runtime_result_class_name(result_names: object, class_id: int) -> str | None:
    """从 YOLOE 运行时结果中读取类别名。"""

    if isinstance(result_names, dict):
        raw_value = result_names.get(class_id)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
    return None


def normalize_runtime_polygon_xy(raw_polygon: object, *, fallback_bbox_xyxy: list[float]) -> list[list[float]]:
    """把运行时 polygon 规整为 workflow 可消费的 polygon_xy。"""

    if isinstance(raw_polygon, np.ndarray) and raw_polygon.ndim == 2 and raw_polygon.shape[1] >= 2:
        return [[float(point[0]), float(point[1])] for point in raw_polygon.tolist()]
    if isinstance(raw_polygon, (list, tuple)) and raw_polygon:
        first_item = raw_polygon[0]
        if isinstance(first_item, np.ndarray) and first_item.ndim == 2 and first_item.shape[1] >= 2:
            return normalize_runtime_polygon_xy(first_item, fallback_bbox_xyxy=fallback_bbox_xyxy)
        if (
            isinstance(first_item, (list, tuple))
            and len(first_item) >= 2
            and isinstance(first_item[0], (int, float))
            and isinstance(first_item[1], (int, float))
        ):
            return [[float(point[0]), float(point[1])] for point in raw_polygon]
        if isinstance(first_item, (list, tuple)) and first_item and isinstance(first_item[0], (list, tuple, np.ndarray)):
            return normalize_runtime_polygon_xy(first_item, fallback_bbox_xyxy=fallback_bbox_xyxy)
    return build_bbox_polygon_xy(fallback_bbox_xyxy)


def build_bbox_polygon_xy(bbox_xyxy: list[float]) -> list[list[float]]:
    """把 bbox_xyxy 转成四点 polygon。"""

    x1_value, y1_value, x2_value, y2_value = bbox_xyxy
    return [
        [float(x1_value), float(y1_value)],
        [float(x2_value), float(y1_value)],
        [float(x2_value), float(y2_value)],
        [float(x1_value), float(y2_value)],
    ]


def encode_runtime_mask_png(mask_tensor: object) -> tuple[bytes | None, int | None, int | None, int]:
    """把运行时 mask tensor 编码成 PNG 字节。"""

    if not torch.is_tensor(mask_tensor):
        return None, None, None, 0
    normalized_mask = (mask_tensor.detach().float().cpu() > 0.5).to(dtype=torch.uint8).numpy() * 255
    if normalized_mask.ndim != 2:
        return None, None, None, 0
    mask_height, mask_width = normalized_mask.shape
    mask_area = int(np.count_nonzero(normalized_mask))
    encoded_image = Image.fromarray(normalized_mask, mode="L")
    buffer = io.BytesIO()
    encoded_image.save(buffer, format="PNG")
    return buffer.getvalue(), int(mask_width), int(mask_height), mask_area


def build_prediction_summary(
    *,
    variant: YoloePretrainedVariant,
    detection_items: list[dict[str, object]],
    region_items: list[dict[str, object]],
    device: str,
    precision: str,
    confidence_threshold: float,
    iou_threshold: float,
    max_detections: int,
    prompt_count: int,
    vocabulary_size: int | None,
) -> dict[str, object]:
    """构造统一的 YOLOE 推理摘要。"""

    summary = {
        "model_series": variant.model_series,
        "model_scale": variant.model_scale,
        "variant_name": variant.variant_name,
        "checkpoint_path": str(variant.checkpoint_path),
        "task_type": variant.task_type,
        "prompt_count": prompt_count,
        "detection_count": len(detection_items),
        "region_count": len(region_items),
        "device": device,
        "precision": precision,
        "confidence_threshold": confidence_threshold,
        "iou_threshold": iou_threshold,
        "max_detections": max_detections,
        "prompt_free": variant.prompt_free,
    }
    if vocabulary_size is not None:
        summary["vocabulary_size"] = vocabulary_size
    return summary


def build_text_prompt_summary_payload(
    *,
    prediction: YoloeDetectionPrediction,
    prompts: tuple[YoloePromptItem, ...],
    image_payload: dict[str, object],
) -> dict[str, object]:
    """构建 text-prompt-detect 节点的 summary payload。"""

    return {
        **prediction.summary,
        "prompt_items": [
            {
                "prompt_id": item.prompt_id,
                "text": item.text,
                "display_name": item.display_name,
                "negative": item.negative,
                **({"language": item.language} if item.language is not None else {}),
            }
            for item in prompts
        ],
        "source_image": build_source_image_summary_payload(image_payload),
    }


def build_prompt_free_summary_payload(
    *,
    prediction: YoloeDetectionPrediction,
    image_payload: dict[str, object],
) -> dict[str, object]:
    """构建 prompt-free 节点 summary payload。"""

    return {
        **prediction.summary,
        "source_image": build_source_image_summary_payload(image_payload),
    }


def build_visual_prompt_summary_payload(
    *,
    prediction: YoloeDetectionPrediction,
    prompts: tuple[YoloeVisualPromptItem, ...],
    image_payload: dict[str, object],
    prompt_image_payload: dict[str, object],
) -> dict[str, object]:
    """构建 visual-prompt-detect 节点 summary payload。"""

    return {
        **prediction.summary,
        "prompt_items": [
            _build_visual_prompt_summary_item(item)
            for item in prompts
        ],
        "source_image": build_source_image_summary_payload(image_payload),
        "prompt_image": build_source_image_summary_payload(prompt_image_payload),
    }


def _build_visual_prompt_summary_item(item: YoloeVisualPromptItem) -> dict[str, object]:
    """构造单条视觉提示的 summary 字段。"""

    payload: dict[str, object] = {
        "prompt_id": item.prompt_id,
        "prompt_kind": item.prompt_kind,
        "display_name": item.display_name,
    }
    if item.prompt_kinds:
        payload["prompt_kinds"] = list(item.prompt_kinds)
    payload["raw_item_count"] = int(item.raw_item_count)
    if item.bbox_xyxy is not None:
        payload["bbox_xyxy"] = list(item.bbox_xyxy)
    if item.point_xy is not None:
        payload["point_xy"] = list(item.point_xy)
    if item.point_label is not None:
        payload["point_label"] = item.point_label
    if item.polygon_xy is not None:
        payload["polygon_xy"] = [list(point) for point in item.polygon_xy]
    if item.prompt_mask is not None:
        payload["has_prompt_mask"] = True
    return payload


def build_source_image_summary_payload(image_payload: dict[str, object]) -> dict[str, object]:
    """提取图片摘要里需要保留的 source image 字段。"""

    return {
        key: image_payload.get(key)
        for key in ("transport_kind", "media_type", "width", "height", "object_key", "image_handle")
        if image_payload.get(key) is not None
    }


def build_regions_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    prediction: YoloeDetectionPrediction,
    image_payload: dict[str, object],
) -> dict[str, object]:
    """把内部 region 结果转换为 workflow regions.v1 payload。"""

    region_items: list[dict[str, object]] = []
    for item in prediction.regions:
        normalized_item = {
            "region_id": item["region_id"],
            "score": item["score"],
            "class_id": item["class_id"],
            "class_name": item["class_name"],
            "bbox_xyxy": list(item["bbox_xyxy"]),
            "polygon_xy": [list(point) for point in item.get("polygon_xy", [])],
            "area": int(item.get("area") or 0),
        }
        if item.get("prompt_id") is not None:
            normalized_item["prompt_id"] = item["prompt_id"]
        if item.get("source_prompt_text") is not None:
            normalized_item["source_prompt_text"] = item["source_prompt_text"]
        if item.get("source_prompt_positive_texts") is not None:
            normalized_item["source_prompt_positive_texts"] = list(item["source_prompt_positive_texts"])
        if item.get("source_prompt_negative_texts") is not None:
            normalized_item["source_prompt_negative_texts"] = list(item["source_prompt_negative_texts"])
        mask_png_bytes = item.get("mask_png_bytes")
        mask_width = item.get("mask_width")
        mask_height = item.get("mask_height")
        if isinstance(mask_png_bytes, bytes) and isinstance(mask_width, int) and isinstance(mask_height, int):
            normalized_item["mask_image"] = register_image_bytes(
                request,
                content=mask_png_bytes,
                media_type="image/png",
                width=mask_width,
                height=mask_height,
            )
        region_items.append(normalized_item)
    return {
        "source_image": build_source_image_summary_payload(image_payload),
        "count": len(region_items),
        "items": region_items,
    }




__all__ = [
    "build_bbox_polygon_xy",
    "build_detection_items_from_runtime_result",
    "build_predict_kwargs",
    "build_prediction_summary",
    "build_prompt_free_summary_payload",
    "build_region_items_from_runtime_result",
    "build_regions_payload",
    "build_source_image_summary_payload",
    "build_text_prompt_summary_payload",
    "build_visual_prompt_summary_payload",
    "encode_runtime_mask_png",
    "normalize_runtime_polygon_xy",
    "read_runtime_result_class_name",
]
