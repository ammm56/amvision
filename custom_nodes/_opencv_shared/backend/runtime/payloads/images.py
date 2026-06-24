"""OpenCV shared image refs payload 工具。"""

from __future__ import annotations

from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes._opencv_shared.backend.runtime.geometry import normalize_bbox
from custom_nodes._opencv_shared.backend.runtime.payloads.common import (
    fill_source_image_fields,
)


def require_image_refs_payload(payload: object) -> dict[str, object]:
    """校验并规范化 image-refs.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("gallery-preview 节点要求 image-refs payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("gallery-preview 节点要求 image-refs.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for item in raw_items:
        normalized_item = require_image_payload(item)
        if isinstance(item, dict):
            if "bbox_xyxy" in item:
                normalized_item["bbox_xyxy"] = list(
                    normalize_bbox(item.get("bbox_xyxy"))
                )
            crop_index = item.get("crop_index")
            if isinstance(crop_index, (int, float)):
                normalized_item["crop_index"] = int(crop_index)
        normalized_items.append(normalized_item)

    normalized_payload = dict(payload)
    normalized_payload["items"] = normalized_items
    normalized_payload["count"] = int(payload.get("count", len(normalized_items)))
    fill_source_image_fields(normalized_payload)
    return normalized_payload
