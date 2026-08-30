"""OpenCV shared 椭圆 payload 工具。"""

from __future__ import annotations

from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.shared.backend.runtime.geometry import (
    normalize_bbox_number,
    normalize_point_xy,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.points import (
    require_coordinate_space,
    require_point_unit,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.validators import require_number


def build_ellipses_payload(
    *,
    items: list[dict[str, object]],
    coordinate_space: str,
    unit: str,
    source_image: object | None = None,
    source_object_key: str | None = None,
) -> dict[str, object]:
    """构建带明确坐标空间的 ellipses.v1。"""

    payload: dict[str, object] = {
        "coordinate_space": require_coordinate_space(coordinate_space),
        "unit": require_point_unit(unit),
        "items": [dict(item) for item in items],
        "count": len(items),
    }
    if isinstance(source_image, dict):
        payload["source_image"] = require_image_payload(source_image)
    if isinstance(source_object_key, str) and source_object_key:
        payload["source_object_key"] = source_object_key
    return require_ellipses_payload(payload)


def require_ellipses_payload(payload: object) -> dict[str, object]:
    """校验并规范化 ellipses.v1。"""

    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise InvalidRequestError("当前节点要求 ellipses.items 必须是数组")
    normalized_items: list[dict[str, object]] = []
    for item_offset, raw_item in enumerate(payload["items"], start=1):
        if not isinstance(raw_item, dict):
            raise InvalidRequestError("当前节点要求每个 ellipse item 必须是对象")
        major_axis = require_number(raw_item.get("major_axis"), field_name="major_axis")
        minor_axis = require_number(raw_item.get("minor_axis"), field_name="minor_axis")
        if major_axis <= 0 or minor_axis <= 0 or major_axis < minor_axis:
            raise InvalidRequestError("ellipse 要求 major_axis >= minor_axis > 0")
        normalized_item = dict(raw_item)
        normalized_item["ellipse_index"] = _require_positive_index(
            raw_item.get("ellipse_index", item_offset)
        )
        normalized_item["center_xy"] = list(
            normalize_point_xy(raw_item.get("center_xy"), field_name="center_xy")
        )
        normalized_item["major_axis"] = major_axis
        normalized_item["minor_axis"] = minor_axis
        normalized_item["angle_deg"] = require_number(
            raw_item.get("angle_deg"), field_name="angle_deg"
        )
        if raw_item.get("bbox_xyxy") is not None:
            normalized_item["bbox_xyxy"] = list(
                normalize_bbox_number(raw_item.get("bbox_xyxy"), field_name="bbox_xyxy")
            )
        normalized_items.append(normalized_item)
    normalized_payload = dict(payload)
    normalized_payload["coordinate_space"] = require_coordinate_space(
        payload.get("coordinate_space", "source-image-pixels")
    )
    normalized_payload["unit"] = require_point_unit(payload.get("unit", "pixel"))
    normalized_payload["items"] = normalized_items
    normalized_payload["count"] = len(normalized_items)
    source_image = payload.get("source_image")
    if isinstance(source_image, dict):
        normalized_payload["source_image"] = require_image_payload(source_image)
    return normalized_payload


def _require_positive_index(raw_value: object) -> int:
    """读取一基椭圆序号。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 1:
        raise InvalidRequestError("ellipse_index 必须是正整数")
    return raw_value


__all__ = ["build_ellipses_payload", "require_ellipses_payload"]
