"""SAM3 custom node 的输入 payload 读取与规范化。"""

from __future__ import annotations

import io
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

from backend.nodes.runtime_support import load_image_bytes, load_image_bytes_from_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.sam3_segment_nodes.backend.payloads.pretrained import SUPPORTED_POINT_LABELS
from custom_nodes.sam3_segment_nodes.backend.payloads.types import (
    Sam3FrameWindowItem,
    Sam3InteractivePromptItem,
    Sam3TextPromptGroup,
    Sam3TextPromptItem,
)


def read_text_prompt_items(payload: object) -> tuple[Sam3TextPromptItem, ...]:
    """把 text-prompts.v1 payload 规范化为语义提示列表。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("SAM3 语义分割节点要求 prompts payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError("SAM3 语义分割节点要求 prompts.items 必须是非空数组")
    prompt_items: list[Sam3TextPromptItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InvalidRequestError("SAM3 语义分割节点要求每个 prompt item 必须是对象")
        prompt_id = str(item.get("prompt_id") or "").strip()
        text = str(item.get("text") or "").strip()
        display_name = str(item.get("display_name") or text).strip()
        negative = bool(item.get("negative"))
        language = str(item.get("language") or "").strip() or None
        if not prompt_id:
            raise InvalidRequestError("SAM3 语义分割节点要求 prompt_id 不能为空")
        if not text:
            raise InvalidRequestError("SAM3 语义分割节点要求 text 不能为空")
        prompt_items.append(
            Sam3TextPromptItem(
                prompt_id=prompt_id,
                text=text,
                display_name=display_name or text,
                negative=negative,
                language=language,
            )
        )
    return tuple(prompt_items)


def merge_text_prompt_items(prompts: tuple[Sam3TextPromptItem, ...]) -> tuple[Sam3TextPromptGroup, ...]:
    """按 prompt_id 聚合 SAM3 文本提示，支持正负文本组合。"""

    grouped_records: dict[str, list[Sam3TextPromptItem | SimpleNamespace]] = {}
    display_name_map: dict[str, str] = {}
    for item in prompts:
        prompt_id = str(getattr(item, "prompt_id", "") or "").strip()
        display_name = str(getattr(item, "display_name", "") or getattr(item, "text", "") or prompt_id).strip() or prompt_id
        if not prompt_id:
            raise InvalidRequestError("SAM3 text prompt 聚合要求 prompt_id 不能为空")
        previous_display_name = display_name_map.get(prompt_id)
        if previous_display_name is not None and previous_display_name != display_name:
            raise InvalidRequestError(
                "同一个 SAM3 text prompt_id 只能对应一个 display_name",
                details={
                    "prompt_id": prompt_id,
                    "display_name": display_name,
                    "previous_display_name": previous_display_name,
                },
            )
        display_name_map[prompt_id] = display_name
        grouped_records.setdefault(prompt_id, []).append(item)

    prompt_groups: list[Sam3TextPromptGroup] = []
    for prompt_id, group_items in grouped_records.items():
        positive_texts = tuple(
            str(getattr(item, "text", "")).strip()
            for item in group_items
            if not bool(getattr(item, "negative", False))
        )
        negative_texts = tuple(
            str(getattr(item, "text", "")).strip()
            for item in group_items
            if bool(getattr(item, "negative", False))
        )
        if not positive_texts:
            raise InvalidRequestError(
                "SAM3 semantic-segment 要求每个 prompt_id 至少包含一条 positive 文本提示",
                details={"prompt_id": prompt_id},
            )
        languages = tuple(
            language
            for language in (
                str(getattr(item, "language", "") or "").strip() or None
                for item in group_items
            )
            if language is not None
        )
        prompt_groups.append(
            Sam3TextPromptGroup(
                prompt_id=prompt_id,
                display_name=display_name_map[prompt_id],
                positive_texts=positive_texts,
                negative_texts=negative_texts,
                languages=languages,
            )
        )
    return tuple(prompt_groups)


def read_interactive_prompt_items(
    payload: object,
    *,
    request: WorkflowNodeExecutionRequest | None = None,
    source_image_payload: dict[str, object] | None = None,
    source_image_bytes: bytes | None = None,
) -> tuple[Sam3InteractivePromptItem, ...]:
    """把 prompt-regions.v1 payload 规范化为当前阶段交互提示列表。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("SAM3 交互分割节点要求 prompts payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError("SAM3 交互分割节点要求 prompts.items 必须是非空数组")
    prompt_items: list[Sam3InteractivePromptItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InvalidRequestError("SAM3 交互分割节点要求每个 prompt item 必须是对象")
        prompt_id = str(item.get("prompt_id") or "").strip()
        prompt_kind = str(item.get("prompt_kind") or "").strip().lower()
        display_name = str(item.get("display_name") or prompt_id).strip() or prompt_id
        if not prompt_id:
            raise InvalidRequestError("SAM3 交互分割节点要求 prompt_id 不能为空")
        if prompt_kind == "box":
            bbox_xyxy = item.get("bbox_xyxy")
            if not isinstance(bbox_xyxy, list) or len(bbox_xyxy) != 4:
                raise InvalidRequestError("SAM3 交互分割节点要求 bbox_xyxy 必须是长度为 4 的数组")
            try:
                normalized_bbox = tuple(float(value) for value in bbox_xyxy)
            except Exception as exc:
                raise InvalidRequestError("SAM3 交互分割节点要求 bbox_xyxy 必须是数字数组") from exc
            prompt_items.append(
                Sam3InteractivePromptItem(
                    prompt_id=prompt_id,
                    prompt_kind=prompt_kind,
                    display_name=display_name,
                    bbox_xyxy=normalized_bbox,
                )
            )
            continue
        if prompt_kind == "point":
            point_xy = item.get("point_xy")
            if not isinstance(point_xy, list) or len(point_xy) != 2:
                raise InvalidRequestError("SAM3 交互分割节点要求 point_xy 必须是长度为 2 的数组")
            try:
                normalized_point = tuple(float(value) for value in point_xy)
            except Exception as exc:
                raise InvalidRequestError("SAM3 交互分割节点要求 point_xy 必须是数字数组") from exc
            point_label = str(item.get("point_label") or "positive").strip().lower()
            if point_label not in SUPPORTED_POINT_LABELS:
                raise InvalidRequestError(
                    "SAM3 交互分割节点要求 point_label 只能是 positive 或 negative",
                    details={"prompt_id": prompt_id, "point_label": point_label},
                )
            prompt_items.append(
                Sam3InteractivePromptItem(
                    prompt_id=prompt_id,
                    prompt_kind=prompt_kind,
                    display_name=display_name,
                    point_xy=normalized_point,
                    point_label=point_label,
                )
            )
            continue
        if prompt_kind == "polygon":
            source_width, source_height = _resolve_source_image_size(
                source_image_payload=source_image_payload,
                source_image_bytes=source_image_bytes,
            )
            normalized_polygon = _normalize_polygon_xy(item.get("polygon_xy"), prompt_id=prompt_id)
            prompt_items.append(
                Sam3InteractivePromptItem(
                    prompt_id=prompt_id,
                    prompt_kind=prompt_kind,
                    display_name=display_name,
                    polygon_xy=normalized_polygon,
                    prompt_mask=_rasterize_polygon_prompt_mask(
                        normalized_polygon,
                        source_width=source_width,
                        source_height=source_height,
                    ),
                )
            )
            continue
        if prompt_kind == "mask":
            if request is None:
                raise InvalidRequestError(
                    "SAM3 交互分割节点解析 mask prompt 时缺少执行请求上下文",
                    details={"prompt_id": prompt_id, "prompt_kind": prompt_kind},
                )
            source_width, source_height = _resolve_source_image_size(
                source_image_payload=source_image_payload,
                source_image_bytes=source_image_bytes,
            )
            _normalized_mask_payload, mask_image_bytes = load_image_bytes_from_payload(
                request,
                image_payload=item.get("mask_image"),
            )
            prompt_items.append(
                Sam3InteractivePromptItem(
                    prompt_id=prompt_id,
                    prompt_kind=prompt_kind,
                    display_name=display_name,
                    prompt_mask=_decode_prompt_mask_image(
                        mask_image_bytes,
                        source_width=source_width,
                        source_height=source_height,
                    ),
                )
            )
            continue
        raise InvalidRequestError(
            "SAM3 交互分割节点要求 prompt_kind 只能是 box、point、polygon 或 mask",
            details={"prompt_id": prompt_id, "prompt_kind": prompt_kind},
        )
    return tuple(prompt_items)


def read_frame_window_items(
    payload: object,
    *,
    request: WorkflowNodeExecutionRequest,
) -> tuple[Sam3FrameWindowItem, ...]:
    """把 frame-window.v1 payload 规范化为可直接推理的帧列表。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("SAM3 视频分割节点要求 frames payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError("SAM3 视频分割节点要求 frames.items 必须是非空数组")

    normalized_items: list[Sam3FrameWindowItem] = []
    expected_frame_size: tuple[int, int] | None = None
    for item_index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            raise InvalidRequestError(
                "SAM3 视频分割节点要求每个 frames.items 都必须是对象",
                details={"item_index": item_index},
            )
        frame_index = raw_item.get("frame_index")
        timestamp_ms = raw_item.get("timestamp_ms")
        if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
            raise InvalidRequestError(
                "SAM3 视频分割节点要求每个 frames.items.frame_index 都必须是非负整数",
                details={"item_index": item_index, "frame_index": frame_index},
            )
        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, (int, float)) or float(timestamp_ms) < 0:
            raise InvalidRequestError(
                "SAM3 视频分割节点要求每个 frames.items.timestamp_ms 都必须是非负数",
                details={"item_index": item_index, "timestamp_ms": timestamp_ms},
            )
        image_payload, image_bytes = load_image_bytes_from_payload(
            request,
            image_payload=raw_item.get("image"),
        )
        source_width, source_height = _resolve_source_image_size(
            source_image_payload=image_payload,
            source_image_bytes=image_bytes,
        )
        current_frame_size = (source_width, source_height)
        if expected_frame_size is None:
            expected_frame_size = current_frame_size
        elif expected_frame_size != current_frame_size:
            raise InvalidRequestError(
                "SAM3 视频分割节点当前阶段要求 frame-window 中所有帧尺寸一致",
                details={
                    "expected_width": expected_frame_size[0],
                    "expected_height": expected_frame_size[1],
                    "actual_width": current_frame_size[0],
                    "actual_height": current_frame_size[1],
                    "item_index": item_index,
                    "frame_index": frame_index,
                },
            )
        normalized_items.append(
            Sam3FrameWindowItem(
                frame_index=frame_index,
                timestamp_ms=float(timestamp_ms),
                image_payload=image_payload,
                image_bytes=image_bytes,
                width=source_width,
                height=source_height,
            )
        )
    return tuple(normalized_items)


def read_image_bytes(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "image",
) -> tuple[dict[str, object], bytes]:
    """读取节点图片输入。"""

    return load_image_bytes(request, input_name=input_name)


def _resolve_source_image_size(
    *,
    source_image_payload: dict[str, object] | None,
    source_image_bytes: bytes | None,
) -> tuple[int, int]:
    """解析 prompt 使用的源图尺寸。"""

    if isinstance(source_image_payload, dict):
        width_value = source_image_payload.get("width")
        height_value = source_image_payload.get("height")
        if isinstance(width_value, (int, float)) and isinstance(height_value, (int, float)):
            normalized_width = int(width_value)
            normalized_height = int(height_value)
            if normalized_width > 0 and normalized_height > 0:
                return normalized_width, normalized_height
    if not isinstance(source_image_bytes, bytes) or not source_image_bytes:
        raise InvalidRequestError("SAM3 polygon prompt 要求能够解析源图尺寸")
    with Image.open(io.BytesIO(source_image_bytes)) as image:
        source_width, source_height = image.size
    if source_width <= 0 or source_height <= 0:
        raise InvalidRequestError("SAM3 polygon prompt 解析出的源图尺寸无效")
    return source_width, source_height


def _normalize_polygon_xy(
    raw_polygon_xy: object,
    *,
    prompt_id: str,
) -> tuple[tuple[float, float], ...]:
    """规范化 polygon prompt 顶点数组。"""

    if not isinstance(raw_polygon_xy, list) or len(raw_polygon_xy) < 3:
        raise InvalidRequestError(
            "SAM3 交互分割节点要求 polygon_xy 至少包含三个点",
            details={"prompt_id": prompt_id},
        )
    normalized_polygon: list[tuple[float, float]] = []
    for point_index, point_value in enumerate(raw_polygon_xy):
        if not isinstance(point_value, list) or len(point_value) != 2:
            raise InvalidRequestError(
                "SAM3 交互分割节点要求 polygon_xy 中的每个点必须是长度为 2 的数组",
                details={"prompt_id": prompt_id, "point_index": point_index},
            )
        try:
            point_x = float(point_value[0])
            point_y = float(point_value[1])
        except Exception as exc:
            raise InvalidRequestError(
                "SAM3 交互分割节点要求 polygon_xy 中的点坐标必须是数字",
                details={"prompt_id": prompt_id, "point_index": point_index},
            ) from exc
        normalized_polygon.append((point_x, point_y))
    return tuple(normalized_polygon)


def _rasterize_polygon_prompt_mask(
    polygon_xy: tuple[tuple[float, float], ...],
    *,
    source_width: int,
    source_height: int,
) -> np.ndarray:
    """把 polygon prompt 栅格化成二值 mask。"""

    if source_width <= 0 or source_height <= 0:
        raise InvalidRequestError("SAM3 polygon prompt 要求源图尺寸必须大于 0")
    mask_image = Image.new("L", (source_width, source_height), color=0)
    draw = ImageDraw.Draw(mask_image)
    draw.polygon([(float(point_x), float(point_y)) for point_x, point_y in polygon_xy], fill=255)
    mask_array = np.asarray(mask_image, dtype=np.uint8)
    return (mask_array > 0).astype(np.uint8)


def _decode_prompt_mask_image(
    image_bytes: bytes,
    *,
    source_width: int,
    source_height: int,
) -> np.ndarray:
    """把 mask_image payload 解码成与源图对齐的二值 mask。"""

    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise InvalidRequestError("SAM3 mask prompt 要求 mask_image 必须包含非空图片字节")
    with Image.open(io.BytesIO(image_bytes)) as image:
        grayscale_image = image.convert("L")
        if grayscale_image.size != (source_width, source_height):
            grayscale_image = grayscale_image.resize((source_width, source_height), resample=Image.Resampling.NEAREST)
        mask_array = np.asarray(grayscale_image, dtype=np.uint8)
    binary_mask = (mask_array > 0).astype(np.uint8)
    if int(binary_mask.sum()) <= 0:
        raise InvalidRequestError("SAM3 mask prompt 解码后的 mask 不能为空")
    return binary_mask


__all__ = [
    "merge_text_prompt_items",
    "read_frame_window_items",
    "read_image_bytes",
    "read_interactive_prompt_items",
    "read_text_prompt_items",
]
