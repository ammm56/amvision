"""YOLOE 节点输入 payload 解析。"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw

from backend.nodes.runtime_support import load_image_bytes, load_image_bytes_from_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.images import decode_image_bytes_to_matrix
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.yoloe_open_vocab_nodes.backend.payloads.types import (
    YoloePromptGroup,
    YoloePromptItem,
    YoloeVisualPromptItem,
)


def decode_image_bytes(image_bytes: bytes, *, image_payload: object = None) -> Image.Image:
    """把图片字节解码为 RGB PIL Image。"""

    try:
        bgr_image = decode_image_bytes_to_matrix(
            cv2_module=cv2,
            np_module=np,
            image_bytes=image_bytes,
            image_payload=image_payload,
            imdecode_flags=cv2.IMREAD_COLOR,
            error_message="YOLOE 节点收到的图片不是有效图像",
            copy_raw=True,
        )
        rgb_image = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb_image, mode="RGB")
    except Exception as exc:  # pragma: no cover - 输入图片损坏时由集成调用触发
        raise InvalidRequestError("YOLOE 节点收到的图片不是有效图像") from exc


def read_text_prompt_items(payload: object) -> tuple[YoloePromptItem, ...]:
    """把 text-prompts.v1 payload 规范化为提示列表。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("YOLOE 文本提示节点要求 prompts payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError("YOLOE 文本提示节点要求 prompts.items 必须是非空数组")
    prompt_items: list[YoloePromptItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InvalidRequestError("YOLOE 文本提示节点要求每个 prompt item 必须是对象")
        prompt_id = str(item.get("prompt_id") or "").strip()
        text = str(item.get("text") or "").strip()
        display_name = str(item.get("display_name") or text).strip()
        negative = bool(item.get("negative"))
        language = str(item.get("language") or "").strip() or None
        if not prompt_id:
            raise InvalidRequestError("YOLOE 文本提示节点要求 prompt_id 不能为空")
        if not text:
            raise InvalidRequestError("YOLOE 文本提示节点要求 text 不能为空")
        prompt_items.append(
            YoloePromptItem(
                prompt_id=prompt_id,
                text=text,
                display_name=display_name or text,
                negative=negative,
                language=language,
            )
        )
    return tuple(prompt_items)


def merge_text_prompt_items(prompts: tuple[YoloePromptItem, ...]) -> tuple[YoloePromptGroup, ...]:
    """按 prompt_id 聚合文本提示，支持正负文本组合。"""

    grouped_records: dict[str, list[YoloePromptItem]] = {}
    display_name_map: dict[str, str] = {}
    for item in prompts:
        prompt_id = str(getattr(item, "prompt_id", "") or "").strip()
        display_name = str(getattr(item, "display_name", "") or getattr(item, "text", "") or prompt_id).strip() or prompt_id
        if not prompt_id:
            raise InvalidRequestError("YOLOE text prompt 聚合要求 prompt_id 不能为空")
        previous_display_name = display_name_map.get(prompt_id)
        if previous_display_name is not None and previous_display_name != display_name:
            raise InvalidRequestError(
                "同一个 YOLOE text prompt_id 只能对应一个 display_name",
                details={
                    "prompt_id": prompt_id,
                    "display_name": display_name,
                    "previous_display_name": previous_display_name,
                },
            )
        display_name_map[prompt_id] = display_name
        grouped_records.setdefault(prompt_id, []).append(item)

    prompt_groups: list[YoloePromptGroup] = []
    for prompt_id, items in grouped_records.items():
        positive_texts = tuple(
            dict.fromkeys(
                str(getattr(item, "text", "") or "").strip()
                for item in items
                if not bool(getattr(item, "negative", False))
            )
        )
        negative_texts = tuple(
            dict.fromkeys(
                str(getattr(item, "text", "") or "").strip()
                for item in items
                if bool(getattr(item, "negative", False))
            )
        )
        positive_texts = tuple(item for item in positive_texts if item)
        negative_texts = tuple(item for item in negative_texts if item)
        if not positive_texts:
            raise InvalidRequestError(
                "YOLOE text prompt 每个 prompt_id 至少要包含一条 positive 文本",
                details={"prompt_id": prompt_id},
            )
        languages = tuple(
            dict.fromkeys(
                str(getattr(item, "language"))
                for item in items
                if getattr(item, "language", None) is not None and str(getattr(item, "language")).strip()
            )
        )
        prompt_groups.append(
            YoloePromptGroup(
                prompt_id=prompt_id,
                display_name=display_name_map[prompt_id],
                positive_texts=positive_texts,
                negative_texts=negative_texts,
                languages=languages,
            )
        )
    return tuple(prompt_groups)


def read_visual_prompt_items(
    payload: object,
    *,
    request: WorkflowNodeExecutionRequest | None = None,
    prompt_image_payload: dict[str, object] | None = None,
    prompt_image_bytes: bytes | None = None,
) -> tuple[YoloeVisualPromptItem, ...]:
    """把 prompt-regions.v1 payload 规范化并按 prompt_id 聚合为 YOLOE 视觉提示列表。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("YOLOE 视觉提示节点要求 prompts payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError("YOLOE 视觉提示节点要求 prompts.items 必须是非空数组")
    prompt_image_size = _resolve_visual_prompt_image_size(
        prompt_image_payload=prompt_image_payload,
        prompt_image_bytes=prompt_image_bytes,
    )
    raw_prompt_records: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InvalidRequestError("YOLOE 视觉提示节点要求每个 prompt item 必须是对象")
        prompt_id = str(item.get("prompt_id") or "").strip()
        prompt_kind = str(item.get("prompt_kind") or "").strip().lower()
        display_name = str(item.get("display_name") or prompt_id).strip() or prompt_id
        if not prompt_id:
            raise InvalidRequestError("YOLOE 视觉提示节点要求 prompt_id 不能为空")
        normalized_bbox: tuple[float, float, float, float] | None = None
        normalized_point_xy: tuple[float, float] | None = None
        normalized_point_label: str | None = None
        normalized_polygon_xy: tuple[tuple[float, float], ...] | None = None
        normalized_prompt_mask: np.ndarray | None = None
        if prompt_kind == "box":
            normalized_bbox = _normalize_visual_prompt_bbox(item.get("bbox_xyxy"))
            normalized_prompt_mask = _rasterize_visual_prompt_box_mask(
                prompt_image_size=prompt_image_size,
                bbox_xyxy=normalized_bbox,
            )
        elif prompt_kind == "point":
            normalized_point_xy = _normalize_visual_prompt_point_xy(item.get("point_xy"))
            normalized_point_label = _normalize_visual_prompt_point_label(item.get("point_label"))
            normalized_prompt_mask = _rasterize_visual_prompt_point_mask(
                prompt_image_size=prompt_image_size,
                point_xy=normalized_point_xy,
            )
        elif prompt_kind == "polygon":
            normalized_polygon_xy = _normalize_visual_prompt_polygon(item.get("polygon_xy"))
            normalized_prompt_mask = _rasterize_visual_prompt_polygon_mask(
                prompt_image_size=prompt_image_size,
                polygon_xy=normalized_polygon_xy,
            )
        elif prompt_kind == "mask":
            if request is None:
                raise InvalidRequestError("YOLOE mask visual prompt 需要节点执行上下文")
            normalized_prompt_mask = _load_visual_prompt_mask(
                request=request,
                mask_image_payload=item.get("mask_image"),
                prompt_image_size=prompt_image_size,
            )
        else:
            raise InvalidRequestError(
                "YOLOE visual-prompt 暂不支持指定的 prompt_kind",
                details={"prompt_id": prompt_id, "prompt_kind": prompt_kind},
            )
        raw_prompt_records.append(
            {
                "prompt_id": prompt_id,
                "prompt_kind": prompt_kind,
                "bbox_xyxy": normalized_bbox,
                "point_xy": normalized_point_xy,
                "point_label": normalized_point_label,
                "polygon_xy": normalized_polygon_xy,
                "prompt_mask": normalized_prompt_mask,
                "display_name": display_name,
            }
        )
    return _merge_visual_prompt_records(raw_prompt_records, prompt_image_size=prompt_image_size)


def read_image_bytes(request: WorkflowNodeExecutionRequest, *, input_name: str = "image") -> tuple[dict[str, object], bytes]:
    """读取节点图片输入。"""

    return load_image_bytes(request, input_name=input_name)


def _resolve_visual_prompt_image_size(
    *,
    prompt_image_payload: dict[str, object] | None,
    prompt_image_bytes: bytes | None,
) -> tuple[int, int]:
    """解析视觉提示参考图尺寸。"""

    width_value = None if prompt_image_payload is None else prompt_image_payload.get("width")
    height_value = None if prompt_image_payload is None else prompt_image_payload.get("height")
    try:
        width = int(width_value) if width_value is not None else 0
        height = int(height_value) if height_value is not None else 0
    except Exception:
        width = 0
        height = 0
    if width > 0 and height > 0:
        return width, height
    if isinstance(prompt_image_bytes, bytes) and prompt_image_bytes:
        prompt_image = decode_image_bytes(prompt_image_bytes, image_payload=prompt_image_payload)
        return int(prompt_image.width), int(prompt_image.height)
    raise InvalidRequestError("YOLOE visual-prompt 无法解析 prompt_image 尺寸")


def _normalize_visual_prompt_bbox(payload: object) -> tuple[float, float, float, float]:
    """规范化 box prompt。"""

    if not isinstance(payload, list) or len(payload) != 4:
        raise InvalidRequestError("YOLOE 视觉提示节点要求 bbox_xyxy 必须是长度为 4 的数组")
    try:
        x1_value, y1_value, x2_value, y2_value = (float(value) for value in payload)
    except Exception as exc:
        raise InvalidRequestError("YOLOE 视觉提示节点要求 bbox_xyxy 必须是数字数组") from exc
    return x1_value, y1_value, x2_value, y2_value


def _normalize_visual_prompt_point_xy(payload: object) -> tuple[float, float]:
    """规范化 point prompt 坐标。"""

    if not isinstance(payload, list) or len(payload) != 2:
        raise InvalidRequestError("YOLOE point visual prompt 要求 point_xy 是长度为 2 的数组")
    try:
        x_value, y_value = (float(value) for value in payload)
    except Exception as exc:
        raise InvalidRequestError("YOLOE point visual prompt 要求 point_xy 必须是数字数组") from exc
    return x_value, y_value


def _normalize_visual_prompt_point_label(value: object) -> str:
    """规范化 point prompt 正负标签。"""

    normalized_value = str(value or "positive").strip().lower()
    if normalized_value not in {"positive", "negative"}:
        raise InvalidRequestError("YOLOE point visual prompt 的 point_label 只能是 positive 或 negative")
    if normalized_value == "negative":
        raise InvalidRequestError("YOLOE visual-prompt 第一阶段暂不支持 negative point")
    return normalized_value


def _normalize_visual_prompt_polygon(payload: object) -> tuple[tuple[float, float], ...]:
    """规范化 polygon prompt 点集。"""

    if not isinstance(payload, list) or len(payload) < 3:
        raise InvalidRequestError("YOLOE polygon visual prompt 要求 polygon_xy 至少包含 3 个点")
    normalized_points: list[tuple[float, float]] = []
    for point in payload:
        if not isinstance(point, list) or len(point) != 2:
            raise InvalidRequestError("YOLOE polygon visual prompt 要求每个 polygon 点都是长度为 2 的数组")
        try:
            normalized_points.append((float(point[0]), float(point[1])))
        except Exception as exc:
            raise InvalidRequestError("YOLOE polygon visual prompt 点坐标必须是数字") from exc
    return tuple(normalized_points)


def _rasterize_visual_prompt_polygon_mask(
    *,
    prompt_image_size: tuple[int, int],
    polygon_xy: tuple[tuple[float, float], ...],
) -> np.ndarray:
    """把 polygon prompt 栅格化成参考图尺寸的二值 mask。"""

    prompt_image_width, prompt_image_height = prompt_image_size
    prompt_mask_image = Image.new("L", (int(prompt_image_width), int(prompt_image_height)), 0)
    draw = ImageDraw.Draw(prompt_mask_image)
    draw.polygon([tuple(float(value) for value in point) for point in polygon_xy], fill=255)
    prompt_mask = np.asarray(prompt_mask_image, dtype=np.uint8)
    return (prompt_mask > 0).astype(np.uint8)


def _rasterize_visual_prompt_box_mask(
    *,
    prompt_image_size: tuple[int, int],
    bbox_xyxy: tuple[float, float, float, float],
) -> np.ndarray:
    """把 box prompt 栅格化成参考图尺寸的二值 mask。"""

    prompt_image_width, prompt_image_height = prompt_image_size
    prompt_mask = np.zeros((int(prompt_image_height), int(prompt_image_width)), dtype=np.uint8)
    x1_value, y1_value, x2_value, y2_value = bbox_xyxy
    x1_index = max(0, min(int(prompt_image_width), int(np.floor(float(x1_value)))))
    y1_index = max(0, min(int(prompt_image_height), int(np.floor(float(y1_value)))))
    x2_index = max(x1_index + 1, min(int(prompt_image_width), int(np.ceil(float(x2_value)))))
    y2_index = max(y1_index + 1, min(int(prompt_image_height), int(np.ceil(float(y2_value)))))
    if x2_index <= x1_index or y2_index <= y1_index:
        return prompt_mask
    prompt_mask[y1_index:y2_index, x1_index:x2_index] = 1
    return prompt_mask


def _rasterize_visual_prompt_point_mask(
    *,
    prompt_image_size: tuple[int, int],
    point_xy: tuple[float, float],
) -> np.ndarray:
    """把 point prompt 栅格化成参考图尺寸的二值 mask。"""

    prompt_image_width, prompt_image_height = prompt_image_size
    prompt_mask = np.zeros((int(prompt_image_height), int(prompt_image_width)), dtype=np.uint8)
    point_x_value, point_y_value = point_xy
    point_x_index = max(0, min(int(prompt_image_width) - 1, int(round(float(point_x_value)))))
    point_y_index = max(0, min(int(prompt_image_height) - 1, int(round(float(point_y_value)))))
    radius = max(1, int(round(min(prompt_image_width, prompt_image_height) / 64.0)))
    x1_index = max(0, point_x_index - radius)
    y1_index = max(0, point_y_index - radius)
    x2_index = min(int(prompt_image_width), point_x_index + radius + 1)
    y2_index = min(int(prompt_image_height), point_y_index + radius + 1)
    prompt_mask[y1_index:y2_index, x1_index:x2_index] = 1
    return prompt_mask


def _load_visual_prompt_mask(
    *,
    request: WorkflowNodeExecutionRequest,
    mask_image_payload: object,
    prompt_image_size: tuple[int, int],
) -> np.ndarray:
    """读取 mask prompt 并规整到参考图尺寸。"""

    normalized_payload, mask_image_bytes = load_image_bytes_from_payload(request, image_payload=mask_image_payload)
    mask_array = decode_image_bytes_to_matrix(
        cv2_module=cv2,
        np_module=np,
        image_bytes=mask_image_bytes,
        image_payload=normalized_payload,
        imdecode_flags=cv2.IMREAD_GRAYSCALE,
        error_message="YOLOE visual-prompt 收到的 mask_image 不是有效图片",
        copy_raw=True,
    )
    prompt_image_width, prompt_image_height = prompt_image_size
    if int(mask_array.shape[1]) != int(prompt_image_width) or int(mask_array.shape[0]) != int(prompt_image_height):
        mask_array = cv2.resize(
            mask_array,
            (int(prompt_image_width), int(prompt_image_height)),
            interpolation=cv2.INTER_NEAREST,
        )
    return (mask_array > 0).astype(np.uint8)


def _merge_visual_prompt_records(
    raw_prompt_records: list[dict[str, object]],
    *,
    prompt_image_size: tuple[int, int],
) -> tuple[YoloeVisualPromptItem, ...]:
    """按 prompt_id 合并多条视觉提示记录。"""

    grouped_records: dict[str, list[dict[str, object]]] = {}
    display_name_map: dict[str, str] = {}
    for record in raw_prompt_records:
        prompt_id = str(record["prompt_id"])
        display_name = str(record["display_name"])
        previous_display_name = display_name_map.get(prompt_id)
        if previous_display_name is not None and previous_display_name != display_name:
            raise InvalidRequestError(
                "同一个 YOLOE visual prompt_id 只能对应一个 display_name",
                details={
                    "prompt_id": prompt_id,
                    "display_name": display_name,
                    "previous_display_name": previous_display_name,
                },
            )
        display_name_map[prompt_id] = display_name
        grouped_records.setdefault(prompt_id, []).append(record)

    merged_items: list[YoloeVisualPromptItem] = []
    prompt_image_width, prompt_image_height = prompt_image_size
    for prompt_id, records in grouped_records.items():
        prompt_kinds = tuple(sorted({str(record["prompt_kind"]) for record in records}))
        merged_mask = np.zeros((int(prompt_image_height), int(prompt_image_width)), dtype=np.uint8)
        for record in records:
            prompt_mask = record.get("prompt_mask")
            if isinstance(prompt_mask, np.ndarray):
                merged_mask = np.maximum(merged_mask, prompt_mask.astype(np.uint8))
        if int(np.count_nonzero(merged_mask)) <= 0:
            merged_prompt_mask: np.ndarray | None = None
        else:
            merged_prompt_mask = merged_mask

        bbox_xyxy: tuple[float, float, float, float] | None = None
        point_xy: tuple[float, float] | None = None
        point_label: str | None = None
        polygon_xy: tuple[tuple[float, float], ...] | None = None
        if len(records) == 1 and len(prompt_kinds) == 1:
            bbox_xyxy = records[0].get("bbox_xyxy") if isinstance(records[0].get("bbox_xyxy"), tuple) else None
            point_xy = records[0].get("point_xy") if isinstance(records[0].get("point_xy"), tuple) else None
            point_label = str(records[0].get("point_label")) if records[0].get("point_label") is not None else None
            polygon_xy = records[0].get("polygon_xy") if isinstance(records[0].get("polygon_xy"), tuple) else None
        elif merged_prompt_mask is not None:
            bbox_xyxy = _compute_visual_prompt_bbox_from_mask(merged_prompt_mask)

        merged_items.append(
            YoloeVisualPromptItem(
                prompt_id=prompt_id,
                prompt_kind=prompt_kinds[0] if len(prompt_kinds) == 1 else "mixed",
                bbox_xyxy=bbox_xyxy,
                point_xy=point_xy,
                point_label=point_label,
                polygon_xy=polygon_xy,
                prompt_mask=merged_prompt_mask,
                display_name=display_name_map[prompt_id],
                prompt_kinds=prompt_kinds,
                raw_item_count=len(records),
            )
        )
    return tuple(merged_items)


def _compute_visual_prompt_bbox_from_mask(prompt_mask: np.ndarray) -> tuple[float, float, float, float] | None:
    """从聚合后的 prompt mask 反推外接框。"""

    if prompt_mask.ndim != 2:
        return None
    mask_indices = np.argwhere(prompt_mask > 0)
    if int(mask_indices.shape[0]) <= 0:
        return None
    y1_index = int(mask_indices[:, 0].min())
    y2_index = int(mask_indices[:, 0].max()) + 1
    x1_index = int(mask_indices[:, 1].min())
    x2_index = int(mask_indices[:, 1].max()) + 1
    return float(x1_index), float(y1_index), float(x2_index), float(y2_index)




__all__ = [
    "decode_image_bytes",
    "merge_text_prompt_items",
    "read_image_bytes",
    "read_text_prompt_items",
    "read_visual_prompt_items",
]
