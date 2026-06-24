"""OpenCV shared payload 构造和规范化工具。"""

from __future__ import annotations

from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes._opencv_shared.backend.runtime.geometry import (
    normalize_bbox,
    normalize_bbox_number,
    normalize_point_xy,
)
from custom_nodes._opencv_shared.backend.runtime.validators import require_number

def iter_detection_items(detections_payload: object) -> list[dict[str, object]]:
    """把 detection payload 规范化为列表。

    参数：
    - detections_payload：原始 detections payload。

    返回：
    - list[dict[str, object]]：规范化后的 detection item 列表。
    """

    if not isinstance(detections_payload, dict):
        raise InvalidRequestError("当前节点要求 detections payload 必须是对象")
    raw_items = detections_payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("当前节点要求 detections.items 必须是数组")
    normalized_items: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InvalidRequestError("当前节点要求每个 detection item 必须是对象")
        normalized_items.append(item)
    return normalized_items

def require_image_refs_payload(payload: object) -> dict[str, object]:
    """校验并规范化 image-refs payload。

    参数：
    - payload：待校验的图片集合 payload。

    返回：
    - dict[str, object]：规范化后的图片集合 payload。
    """

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
                normalized_item["bbox_xyxy"] = list(normalize_bbox(item.get("bbox_xyxy")))
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

def require_contours_payload(payload: object) -> dict[str, object]:
    """校验并规范化 contours payload。

    参数：
    - payload：待校验的 contour payload。

    返回：
    - dict[str, object]：规范化后的 contour payload。
    """

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
                raise InvalidRequestError("当前节点要求 contour.points 中的每个点必须包含 x 与 y")
            point_x, point_y = point[:2]
            normalized_points.append([int(round(float(point_x))), int(round(float(point_y)))])
        normalized_item = dict(item)
        normalized_item["contour_index"] = int(item.get("contour_index", index))
        normalized_item["point_count"] = int(item.get("point_count", len(normalized_points)))
        normalized_item["bbox_xyxy"] = list(normalize_bbox(item.get("bbox_xyxy")))
        normalized_item["points"] = normalized_points
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

def build_circles_payload(
    *,
    items: list[dict[str, object]],
    source_image: object | None,
    source_object_key: str | None,
) -> dict[str, object]:
    """构建规范化后的 circles.v1 payload。"""

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
        normalized_item["start_xy"] = list(normalize_point_xy(item.get("start_xy"), field_name="start_xy"))
        normalized_item["end_xy"] = list(normalize_point_xy(item.get("end_xy"), field_name="end_xy"))
        normalized_item["length_pixels"] = require_number(item.get("length_pixels"), field_name="length_pixels")
        normalized_item["angle_deg"] = require_number(item.get("angle_deg"), field_name="angle_deg")
        if "midpoint_xy" in item:
            normalized_item["midpoint_xy"] = list(normalize_point_xy(item.get("midpoint_xy"), field_name="midpoint_xy"))
        if "bbox_xyxy" in item:
            normalized_item["bbox_xyxy"] = list(normalize_bbox_number(item.get("bbox_xyxy"), field_name="bbox_xyxy"))
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

def require_circles_payload(payload: object) -> dict[str, object]:
    """校验并规范化 circles.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("当前节点要求 circles payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("当前节点要求 circles.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise InvalidRequestError("当前节点要求每个 circle item 必须是对象")
        circle_index = item.get("circle_index", index)
        if isinstance(circle_index, bool) or not isinstance(circle_index, int):
            raise InvalidRequestError("当前节点要求 circle_index 必须是整数")
        normalized_item = dict(item)
        normalized_item["circle_index"] = int(circle_index)
        normalized_item["center_xy"] = list(normalize_point_xy(item.get("center_xy"), field_name="center_xy"))
        normalized_item["radius"] = require_number(item.get("radius"), field_name="radius")
        normalized_item["diameter"] = require_number(item.get("diameter"), field_name="diameter")
        normalized_item["area"] = require_number(item.get("area"), field_name="area")
        if "bbox_xyxy" in item:
            normalized_item["bbox_xyxy"] = list(normalize_bbox_number(item.get("bbox_xyxy"), field_name="bbox_xyxy"))
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

def build_detection_label(*, item: dict[str, object], draw_scores: bool) -> str:
    """根据 detection item 生成要绘制的标签文本。

    参数：
    - item：单个 detection item。
    - draw_scores：是否附带 score。

    返回：
    - str：要绘制的标签文本。
    """

    label_parts: list[str] = []
    class_name = item.get("class_name")
    if isinstance(class_name, str) and class_name.strip():
        label_parts.append(class_name.strip())
    score = item.get("score")
    if draw_scores and isinstance(score, (int, float)):
        label_parts.append(f"{float(score):.2f}")
    return " ".join(label_parts)
