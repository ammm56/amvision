"""OpenCV shared lines payload 工具。"""

from __future__ import annotations

from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes._opencv_shared.backend.runtime.geometry import (
    normalize_bbox_number,
    normalize_point_xy,
)
from custom_nodes._opencv_shared.backend.runtime.payloads.common import (
    fill_source_image_fields,
)
from custom_nodes._opencv_shared.backend.runtime.validators import require_number


def build_lines_payload(
    *,
    items: list[dict[str, object]],
    source_image: object | None,
    source_object_key: str | None,
) -> dict[str, object]:
    """构建规范化后的 lines.v1 payload。"""

    payload: dict[str, object] = {
        "items": [dict(item) for item in items],
        "count": len(items),
    }
    if isinstance(source_image, dict):
        payload["source_image"] = require_image_payload(source_image)
    if isinstance(source_object_key, str) and source_object_key:
        payload["source_object_key"] = source_object_key
    return payload


def require_lines_payload(payload: object) -> dict[str, object]:
    """校验并规范化 lines.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("当前节点要求 lines payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("当前节点要求 lines.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise InvalidRequestError("当前节点要求每个 line item 必须是对象")
        line_index = item.get("line_index", index)
        if isinstance(line_index, bool) or not isinstance(line_index, int):
            raise InvalidRequestError("当前节点要求 line_index 必须是整数")
        normalized_item = dict(item)
        normalized_item["line_index"] = int(line_index)
        normalized_item["start_xy"] = list(
            normalize_point_xy(item.get("start_xy"), field_name="start_xy")
        )
        normalized_item["end_xy"] = list(
            normalize_point_xy(item.get("end_xy"), field_name="end_xy")
        )
        normalized_item["length_pixels"] = require_number(
            item.get("length_pixels"), field_name="length_pixels"
        )
        normalized_item["angle_deg"] = require_number(
            item.get("angle_deg"), field_name="angle_deg"
        )
        if "midpoint_xy" in item:
            normalized_item["midpoint_xy"] = list(
                normalize_point_xy(item.get("midpoint_xy"), field_name="midpoint_xy")
            )
        if "bbox_xyxy" in item:
            normalized_item["bbox_xyxy"] = list(
                normalize_bbox_number(item.get("bbox_xyxy"), field_name="bbox_xyxy")
            )
        normalized_items.append(normalized_item)

    normalized_payload = dict(payload)
    normalized_payload["items"] = normalized_items
    normalized_payload["count"] = int(payload.get("count", len(normalized_items)))
    fill_source_image_fields(normalized_payload)
    return normalized_payload
