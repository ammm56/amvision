"""OpenCV shared contours payload 工具。"""

from __future__ import annotations

from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes._opencv_shared.backend.runtime.geometry import normalize_bbox
from custom_nodes._opencv_shared.backend.runtime.payloads.common import (
    fill_source_image_fields,
)


def require_contours_payload(payload: object) -> dict[str, object]:
    """校验并规范化 contours.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("当前节点要求 contours payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("当前节点要求 contours.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise InvalidRequestError("当前节点要求每个 contour item 必须是对象")
        raw_points = item.get("points")
        if not isinstance(raw_points, list) or len(raw_points) < 3:
            raise InvalidRequestError("当前节点要求 contour.points 至少包含三个点")
        normalized_points: list[list[int]] = []
        for point in raw_points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                raise InvalidRequestError(
                    "当前节点要求 contour.points 中的每个点必须包含 x 与 y"
                )
            point_x, point_y = point[:2]
            normalized_points.append(
                [int(round(float(point_x))), int(round(float(point_y)))]
            )
        normalized_item = dict(item)
        normalized_item["contour_index"] = int(item.get("contour_index", index))
        normalized_item["point_count"] = int(
            item.get("point_count", len(normalized_points))
        )
        normalized_item["bbox_xyxy"] = list(normalize_bbox(item.get("bbox_xyxy")))
        normalized_item["points"] = normalized_points
        normalized_items.append(normalized_item)

    normalized_payload = dict(payload)
    normalized_payload["items"] = normalized_items
    normalized_payload["count"] = int(payload.get("count", len(normalized_items)))
    fill_source_image_fields(normalized_payload)
    return normalized_payload


def build_contours_payload(
    *,
    items: list[dict[str, object]],
    source_image: object | None,
    source_object_key: str | None,
) -> dict[str, object]:
    """构建规范化后的 contours.v1 payload。"""

    payload: dict[str, object] = {
        "items": [dict(item) for item in items],
        "count": len(items),
    }
    if isinstance(source_image, dict):
        payload["source_image"] = require_image_payload(source_image)
    if isinstance(source_object_key, str) and source_object_key:
        payload["source_object_key"] = source_object_key
    return payload


def resolve_contours_source_image(
    *,
    contours_payload: dict[str, object],
    image_payload: object | None,
) -> dict[str, object] | None:
    """优先读取显式 image 输入，否则回退到 contours.source_image。"""

    if image_payload is not None:
        return require_image_payload(image_payload)
    source_image = contours_payload.get("source_image")
    if isinstance(source_image, dict):
        return require_image_payload(source_image)
    return None
