"""OpenCV shared 二维定位结果 payload 工具。"""

from __future__ import annotations

from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.shared.backend.runtime.geometry import normalize_point_xy
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.points import (
    require_coordinate_space,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.transforms import (
    require_planar_transform_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.validators import (
    require_non_negative_int,
    require_number,
)


def build_localizations_payload(
    *,
    items: list[dict[str, object]],
    coordinate_space: str,
    source_image: object | None = None,
    reference_image: object | None = None,
) -> dict[str, object]:
    """构建并规范化 localizations.v1 payload。"""

    payload: dict[str, object] = {
        "coordinate_space": coordinate_space,
        "angle_unit": "degrees",
        "count": len(items),
        "items": items,
    }
    if source_image is not None:
        payload["source_image"] = source_image
    if reference_image is not None:
        payload["reference_image"] = reference_image
    return require_localizations_payload(payload)


def require_localizations_payload(payload: object) -> dict[str, object]:
    """校验并规范化 localizations.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("当前节点要求 localizations payload 必须是对象")
    coordinate_space = require_coordinate_space(payload.get("coordinate_space"))
    if payload.get("angle_unit") != "degrees":
        raise InvalidRequestError("localizations.angle_unit 必须是 degrees")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("localizations.items 必须是数组")
    declared_count = require_non_negative_int(payload.get("count"), field_name="count")
    if declared_count != len(raw_items):
        raise InvalidRequestError("localizations.count 必须与 items 数量一致")

    normalized_items: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise InvalidRequestError("每个 localization item 必须是对象")
        localization_id = _require_text(
            raw_item.get("localization_id"),
            field_name="localization_id",
        )
        if localization_id in seen_ids:
            raise InvalidRequestError("localization_id 不能重复")
        method = _require_text(raw_item.get("method"), field_name="method")
        scale = require_number(raw_item.get("scale"), field_name="scale")
        if scale <= 0.0:
            raise InvalidRequestError("localization.scale 必须大于 0")
        score = require_number(raw_item.get("score"), field_name="score")
        if score < 0.0 or score > 1.0:
            raise InvalidRequestError("localization.score 必须在 0 到 1 之间")
        transform = require_planar_transform_payload(raw_item.get("transform"))
        if transform["target_coordinate_space"] != coordinate_space:
            raise InvalidRequestError(
                "localization.transform.target_coordinate_space 必须与顶层 coordinate_space 一致"
            )

        normalized_item: dict[str, object] = {
            "localization_id": localization_id,
            "method": method,
            "center_xy": list(
                normalize_point_xy(raw_item.get("center_xy"), field_name="center_xy")
            ),
            "angle_degrees": require_number(
                raw_item.get("angle_degrees"),
                field_name="angle_degrees",
            ),
            "scale": scale,
            "score": score,
            "transform": transform,
        }
        for optional_object_name in ("roi", "region", "diagnostics"):
            optional_value = raw_item.get(optional_object_name)
            if optional_value is not None:
                if not isinstance(optional_value, dict):
                    raise InvalidRequestError(
                        f"localization.{optional_object_name} 必须是对象"
                    )
                normalized_item[optional_object_name] = dict(optional_value)
        seen_ids.add(localization_id)
        normalized_items.append(normalized_item)

    normalized_payload: dict[str, object] = {
        "coordinate_space": coordinate_space,
        "angle_unit": "degrees",
        "count": len(normalized_items),
        "items": normalized_items,
    }
    for image_field in ("source_image", "reference_image"):
        raw_image = payload.get(image_field)
        if raw_image is not None:
            normalized_payload[image_field] = require_image_payload(raw_image)
    return normalized_payload


def _require_text(raw_value: object, *, field_name: str) -> str:
    """读取长度有界的非空文本。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{field_name} 必须是非空字符串")
    normalized_value = raw_value.strip()
    if len(normalized_value) > 128:
        raise InvalidRequestError(f"{field_name} 长度不能超过 128")
    return normalized_value


__all__ = ["build_localizations_payload", "require_localizations_payload"]
