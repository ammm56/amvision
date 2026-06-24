"""Barcode/QR 节点结果 payload、位置和摘要工具。"""

from __future__ import annotations

from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError


def require_image_refs_payload(payload: object) -> dict[str, object]:
    """校验并规范化 image-refs payload。

    参数：
    - payload：待校验的图片集合 payload。

    返回：
    - dict[str, object]：规范化后的图片集合 payload。
    """

    if not isinstance(payload, dict):
        raise InvalidRequestError("barcode 节点要求 image-refs payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("barcode 节点要求 image-refs.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for item in raw_items:
        normalized_item = require_image_payload(item)
        if isinstance(item, dict):
            raw_bbox = item.get("bbox_xyxy")
            if isinstance(raw_bbox, list) and len(raw_bbox) == 4:
                normalized_item["bbox_xyxy"] = [int(value) for value in raw_bbox]
            crop_index = item.get("crop_index")
            if isinstance(crop_index, (int, float)):
                normalized_item["crop_index"] = int(crop_index)
        normalized_items.append(normalized_item)

    normalized_payload = dict(payload)
    normalized_payload["items"] = normalized_items
    normalized_payload["count"] = int(payload.get("count", len(normalized_items)))
    source_image = payload.get("source_image")
    if isinstance(source_image, dict):
        normalized_payload["source_image"] = require_image_payload(source_image)
    resolved_source_object_key = normalized_payload.get("source_object_key")
    if not isinstance(resolved_source_object_key, str) or not resolved_source_object_key:
        normalized_source_image = normalized_payload.get("source_image")
        if isinstance(normalized_source_image, dict):
            source_object_key = normalized_source_image.get("object_key")
            if isinstance(source_object_key, str) and source_object_key:
                normalized_payload["source_object_key"] = source_object_key
    return normalized_payload


def require_barcode_results_payload(payload: object) -> dict[str, object]:
    """校验并规范化 barcode-results payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("barcode 节点要求 barcode-results payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("barcode-results.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise InvalidRequestError("barcode-results.items 中的每一项都必须是对象")
        normalized_item = dict(item)
        normalized_item["index"] = int(item.get("index", index))
        normalized_item["position"] = require_barcode_position_payload(item.get("position"))
        normalized_items.append(normalized_item)

    normalized_payload = dict(payload)
    normalized_payload["items"] = normalized_items
    normalized_payload["count"] = int(payload.get("count", len(normalized_items)))
    matched_formats = payload.get("matched_formats")
    if isinstance(matched_formats, list):
        normalized_payload["matched_formats"] = [str(item) for item in matched_formats]
    else:
        normalized_payload["matched_formats"] = [
            str(item.get("format")) for item in normalized_items if isinstance(item.get("format"), str)
        ]
    source_image = payload.get("source_image")
    if isinstance(source_image, dict):
        normalized_payload["source_image"] = require_image_payload(source_image)
    resolved_source_object_key = normalized_payload.get("source_object_key")
    if not isinstance(resolved_source_object_key, str) or not resolved_source_object_key:
        normalized_source_image = normalized_payload.get("source_image")
        if isinstance(normalized_source_image, dict):
            source_object_key = normalized_source_image.get("object_key")
            if isinstance(source_object_key, str) and source_object_key:
                normalized_payload["source_object_key"] = source_object_key
    return normalized_payload


def build_barcode_results_summary(results_payload: object) -> dict[str, object]:
    """把 barcode-results payload 转换为更轻量的业务摘要对象。

    参数：
    - results_payload：输入的 barcode-results.v1 payload。

    返回：
    - dict[str, object]：便于 workflow 分支直接读取的摘要结构。
    """

    normalized_payload = require_barcode_results_payload(results_payload)
    items = normalized_payload["items"]
    summary_items = [_build_summary_item(item) for item in items]
    format_counts: dict[str, int] = {}
    texts: list[str] = []
    indices: list[int] = []
    valid_count = 0

    for item in items:
        item_format = item.get("format")
        if isinstance(item_format, str) and item_format:
            format_counts[item_format] = format_counts.get(item_format, 0) + 1
        item_text = item.get("text")
        if isinstance(item_text, str):
            texts.append(item_text)
        indices.append(int(item.get("index", 0)))
        if bool(item.get("valid", False)):
            valid_count += 1

    first_item = items[0] if items else None
    return {
        "type": "barcode-results-summary.v1",
        "requested_format": normalized_payload.get("requested_format"),
        "source_object_key": normalized_payload.get("source_object_key"),
        "count": len(items),
        "has_items": bool(items),
        "matched_formats": list(normalized_payload.get("matched_formats", [])),
        "items": summary_items,
        "indices": indices,
        "texts": texts,
        "format_counts": format_counts,
        "valid_count": valid_count,
        "invalid_count": len(items) - valid_count,
        "all_valid": valid_count == len(items),
        "first_index": int(first_item.get("index", 0)) if isinstance(first_item, dict) else None,
        "first_text": first_item.get("text") if isinstance(first_item, dict) else None,
        "first_format": first_item.get("format") if isinstance(first_item, dict) else None,
        "first_item": _build_summary_item(first_item) if isinstance(first_item, dict) else None,
    }


def require_barcode_position_payload(payload: object) -> dict[str, object]:
    """校验并规范化单个条码结果中的 position 结构。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("barcode 结果中的 position 必须是对象")
    polygon_xy = payload.get("polygon_xy")
    if not isinstance(polygon_xy, list) or len(polygon_xy) < 4:
        raise InvalidRequestError("barcode position.polygon_xy 至少包含四个点")
    normalized_polygon_xy = [normalize_xy_point(point) for point in polygon_xy[:4]]

    normalized_payload = dict(payload)
    normalized_payload["polygon_xy"] = normalized_polygon_xy
    for field_name in ("top_left_xy", "top_right_xy", "bottom_right_xy", "bottom_left_xy"):
        if field_name in payload:
            normalized_payload[field_name] = normalize_xy_point(payload[field_name])
    if "top_left_xy" not in normalized_payload:
        normalized_payload["top_left_xy"] = normalized_polygon_xy[0]
    if "top_right_xy" not in normalized_payload:
        normalized_payload["top_right_xy"] = normalized_polygon_xy[1]
    if "bottom_right_xy" not in normalized_payload:
        normalized_payload["bottom_right_xy"] = normalized_polygon_xy[2]
    if "bottom_left_xy" not in normalized_payload:
        normalized_payload["bottom_left_xy"] = normalized_polygon_xy[3]

    bounds_xyxy = payload.get("bounds_xyxy")
    if isinstance(bounds_xyxy, (list, tuple)) and len(bounds_xyxy) >= 4:
        normalized_payload["bounds_xyxy"] = [int(round(float(value))) for value in bounds_xyxy[:4]]
    else:
        normalized_payload["bounds_xyxy"] = build_bounds_xyxy(normalized_polygon_xy)

    center_xy = payload.get("center_xy")
    if isinstance(center_xy, (list, tuple)) and len(center_xy) >= 2:
        normalized_payload["center_xy"] = [float(center_xy[0]), float(center_xy[1])]
    else:
        x1, y1, x2, y2 = normalized_payload["bounds_xyxy"]
        normalized_payload["center_xy"] = [(float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0]

    size_wh = payload.get("size_wh")
    if isinstance(size_wh, (list, tuple)) and len(size_wh) >= 2:
        normalized_payload["size_wh"] = [int(round(float(size_wh[0]))), int(round(float(size_wh[1])))]
    else:
        x1, y1, x2, y2 = normalized_payload["bounds_xyxy"]
        normalized_payload["size_wh"] = [int(x2 - x1), int(y2 - y1)]
    return normalized_payload


def iter_barcode_result_items(results_payload: object) -> list[dict[str, object]]:
    """把 barcode-results payload 规范化为结果项列表。"""

    return list(require_barcode_results_payload(results_payload)["items"])


def rebuild_barcode_results_payload(
    normalized_payload: dict[str, object],
    filtered_items: list[dict[str, object]],
) -> dict[str, object]:
    """基于筛选后的结果项重建 barcode-results payload。"""

    rebuilt_payload: dict[str, object] = {
        "requested_format": normalized_payload.get("requested_format"),
        "count": len(filtered_items),
        "matched_formats": list(
            dict.fromkeys(
                item.get("format")
                for item in filtered_items
                if isinstance(item.get("format"), str) and item.get("format")
            )
        ),
        "items": [dict(item) for item in filtered_items],
    }
    source_image = normalized_payload.get("source_image")
    if isinstance(source_image, dict):
        rebuilt_payload["source_image"] = dict(source_image)
    source_object_key = normalized_payload.get("source_object_key")
    if isinstance(source_object_key, str) and source_object_key:
        rebuilt_payload["source_object_key"] = source_object_key
    return rebuilt_payload


def build_barcode_label(
    *,
    item: dict[str, object],
    draw_text: bool,
    draw_format: bool,
    draw_index: bool,
) -> str:
    """根据 barcode 结果项生成叠加绘制标签文本。"""

    label_parts: list[str] = []
    if draw_index:
        label_parts.append(f"#{int(item.get('index', 0))}")
    if draw_format:
        item_format = item.get("format")
        if isinstance(item_format, str) and item_format.strip():
            label_parts.append(item_format.strip())
    if draw_text:
        item_text = item.get("text")
        if isinstance(item_text, str) and item_text.strip():
            label_parts.append(item_text.strip())
    return " | ".join(label_parts)


def normalize_xy_point(raw_point: object) -> list[int]:
    """把任意两点数组规范化为 [x, y] 整数坐标。"""

    if not isinstance(raw_point, (list, tuple)) or len(raw_point) < 2:
        raise InvalidRequestError("position 中的点必须包含 x 与 y")
    return [int(round(float(raw_point[0]))), int(round(float(raw_point[1])))]


def build_bounds_xyxy(polygon_xy: list[list[int]]) -> list[int]:
    """从四点 polygon 计算位置参考矩形。"""

    x_values = [point[0] for point in polygon_xy]
    y_values = [point[1] for point in polygon_xy]
    return [min(x_values), min(y_values), max(x_values), max(y_values)]


def _build_summary_item(item: dict[str, object]) -> dict[str, object]:
    """提取单个条码结果的轻量摘要。"""

    summary_item: dict[str, object] = {
        "index": int(item.get("index", 0)),
        "format": item.get("format"),
        "text": item.get("text"),
        "valid": bool(item.get("valid", False)),
    }
    item_position = item.get("position")
    if isinstance(item_position, dict) and "bounds_xyxy" in item_position:
        summary_item["bounds_xyxy"] = list(item_position["bounds_xyxy"])
    return summary_item
