"""OpenCV shared 二维点 payload 工具。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.shared.backend.runtime.geometry import normalize_point_xy
from custom_nodes.opencv_nodes.shared.backend.runtime.validators import (
    require_non_negative_int,
    require_number,
)


SUPPORTED_POINT_UNITS = {"pixel", "millimeter", "meter", "unitless"}


def require_coordinate_space(raw_value: object, *, field_name: str = "coordinate_space") -> str:
    """读取稳定、非空的坐标空间标识。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{field_name} 必须是非空字符串")
    normalized_value = raw_value.strip()
    if len(normalized_value) > 128:
        raise InvalidRequestError(f"{field_name} 长度不能超过 128")
    return normalized_value


def require_point_unit(raw_value: object) -> str:
    """读取二维点坐标单位。"""

    if not isinstance(raw_value, str):
        raise InvalidRequestError("unit 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in SUPPORTED_POINT_UNITS:
        raise InvalidRequestError(
            "unit 仅支持 pixel、millimeter、meter 或 unitless",
        )
    return normalized_value


def build_points_payload(
    *,
    items: list[dict[str, object]],
    coordinate_space: str,
    unit: str,
) -> dict[str, object]:
    """构建并规范化 points.v1 payload。"""

    return require_points_payload(
        {
            "coordinate_space": coordinate_space,
            "unit": unit,
            "count": len(items),
            "items": items,
        }
    )


def require_points_payload(payload: object) -> dict[str, object]:
    """校验并规范化 points.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("当前节点要求 points payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("当前节点要求 points.items 必须是数组")

    coordinate_space = require_coordinate_space(payload.get("coordinate_space"))
    unit = require_point_unit(payload.get("unit"))
    declared_count = require_non_negative_int(payload.get("count"), field_name="count")
    if declared_count != len(raw_items):
        raise InvalidRequestError("points.count 必须与 items 数量一致")

    normalized_items: list[dict[str, object]] = []
    seen_point_ids: set[str] = set()
    seen_point_indexes: set[int] = set()
    for item_offset, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise InvalidRequestError("当前节点要求每个 point item 必须是对象")
        point_id = raw_item.get("point_id")
        if not isinstance(point_id, str) or not point_id.strip():
            raise InvalidRequestError("point_id 必须是非空字符串")
        normalized_point_id = point_id.strip()
        if normalized_point_id in seen_point_ids:
            raise InvalidRequestError("points.items 中的 point_id 不能重复")
        point_index = require_non_negative_int(
            raw_item.get("point_index", item_offset),
            field_name="point_index",
        )
        if point_index in seen_point_indexes:
            raise InvalidRequestError("points.items 中的 point_index 不能重复")

        normalized_item: dict[str, object] = {
            "point_id": normalized_point_id,
            "point_index": point_index,
            "xy": list(normalize_point_xy(raw_item.get("xy"), field_name="xy")),
        }
        label = raw_item.get("label")
        if label is not None:
            if not isinstance(label, str):
                raise InvalidRequestError("point.label 必须是字符串")
            normalized_item["label"] = label
        score = raw_item.get("score")
        if score is not None:
            normalized_score = require_number(score, field_name="point.score")
            if normalized_score < 0.0 or normalized_score > 1.0:
                raise InvalidRequestError("point.score 必须在 0 到 1 之间")
            normalized_item["score"] = normalized_score
        diagnostics = raw_item.get("diagnostics")
        if diagnostics is not None:
            if not isinstance(diagnostics, dict):
                raise InvalidRequestError("point.diagnostics 必须是对象")
            normalized_item["diagnostics"] = dict(diagnostics)

        seen_point_ids.add(normalized_point_id)
        seen_point_indexes.add(point_index)
        normalized_items.append(normalized_item)

    return {
        "coordinate_space": coordinate_space,
        "unit": unit,
        "count": len(normalized_items),
        "items": normalized_items,
    }


__all__ = [
    "SUPPORTED_POINT_UNITS",
    "build_points_payload",
    "require_coordinate_space",
    "require_point_unit",
    "require_points_payload",
]
