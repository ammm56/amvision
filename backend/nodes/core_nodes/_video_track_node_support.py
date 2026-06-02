"""视频 tracks core 节点共享 helper。"""

from __future__ import annotations

from collections.abc import Iterable

from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError


def require_tracks_payload(payload: object, *, node_id: str, field_name: str = "tracks") -> dict[str, object]:
    """校验 tracks.v1 payload 并返回规范化结果。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError(
            f"{field_name} payload 必须是对象",
            details={"node_id": node_id},
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError(
            f"{field_name}.items 必须是数组",
            details={"node_id": node_id},
        )
    normalized_items: list[dict[str, object]] = []
    for item_index, raw_item in enumerate(raw_items, start=1):
        normalized_items.append(
            _normalize_track_item(
                raw_item,
                node_id=node_id,
                field_name=field_name,
                item_index=item_index,
            )
        )
    return {
        "source_video": payload.get("source_video"),
        "items": tuple(normalized_items),
    }


def require_regions_payload(payload: object, *, node_id: str, field_name: str = "regions") -> dict[str, object]:
    """校验 regions.v1 payload 并返回规范化结果。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError(
            f"{field_name} payload 必须是对象",
            details={"node_id": node_id},
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError(
            f"{field_name}.items 必须是数组",
            details={"node_id": node_id},
        )
    normalized_items: list[dict[str, object]] = []
    for item_index, raw_item in enumerate(raw_items, start=1):
        normalized_items.append(
            _normalize_region_item(
                raw_item,
                node_id=node_id,
                field_name=field_name,
                item_index=item_index,
            )
        )
    selected_frame_index = payload.get("selected_frame_index")
    if selected_frame_index is not None and (
        isinstance(selected_frame_index, bool)
        or not isinstance(selected_frame_index, int)
        or selected_frame_index < 0
    ):
        raise InvalidRequestError(
            f"{field_name}.selected_frame_index 必须是非负整数",
            details={"node_id": node_id, "selected_frame_index": selected_frame_index},
        )
    return {
        "source_image": payload.get("source_image"),
        "selected_frame_index": selected_frame_index,
        "items": tuple(normalized_items),
    }


def build_tracks_payload(*, source_video: object, items: Iterable[dict[str, object]]) -> dict[str, object]:
    """构建规范化后的 tracks.v1 payload。"""

    normalized_items = [dict(item) for item in items]
    return {
        "source_video": source_video if isinstance(source_video, dict) else {},
        "count": len(normalized_items),
        "items": normalized_items,
    }


def build_regions_payload_from_tracks(
    *,
    track_items: Iterable[dict[str, object]],
    selected_frame_index: int | None,
) -> dict[str, object]:
    """把 tracks 项转换成 regions.v1 payload。"""

    region_items: list[dict[str, object]] = []
    for item_index, track_item in enumerate(track_items, start=1):
        bbox_xyxy = track_item.get("bbox_xyxy")
        polygon_xy = track_item.get("polygon_xy")
        area = track_item.get("area")
        if not isinstance(bbox_xyxy, list) or len(bbox_xyxy) != 4:
            raise InvalidRequestError(
                "tracks-to-regions 节点要求每个 track 都包含有效 bbox_xyxy",
                details={"item_index": item_index, "track_id": track_item.get("track_id")},
            )
        if not isinstance(polygon_xy, list):
            raise InvalidRequestError(
                "tracks-to-regions 节点要求每个 track 都包含有效 polygon_xy",
                details={"item_index": item_index, "track_id": track_item.get("track_id")},
            )
        if isinstance(area, bool) or not isinstance(area, int) or area < 0:
            raise InvalidRequestError(
                "tracks-to-regions 节点要求每个 track 都包含有效 area",
                details={"item_index": item_index, "track_id": track_item.get("track_id"), "area": area},
            )
        normalized_region = {
            "region_id": str(track_item.get("region_id") or f"{track_item['track_id']}:{track_item['frame_index']}"),
            "score": float(track_item["score"]),
            "class_id": int(track_item["class_id"]) if isinstance(track_item.get("class_id"), int) else 0,
            "class_name": str(track_item.get("class_name") or ""),
            "bbox_xyxy": list(bbox_xyxy),
            "polygon_xy": [list(point) for point in polygon_xy],
            "area": area,
            "track_id": track_item["track_id"],
            "frame_index": track_item["frame_index"],
            "timestamp_ms": track_item["timestamp_ms"],
            "state": track_item.get("state"),
        }
        if isinstance(track_item.get("mask_image"), dict):
            normalized_region["mask_image"] = dict(track_item["mask_image"])
        for optional_field in (
            "prompt_id",
            "source_prompt_text",
            "source_prompt_positive_texts",
            "source_prompt_negative_texts",
        ):
            if optional_field in track_item:
                normalized_region[optional_field] = track_item[optional_field]
        region_items.append(normalized_region)
    return {
        "count": len(region_items),
        "items": region_items,
        **({"selected_frame_index": selected_frame_index} if selected_frame_index is not None else {}),
    }


def filter_track_items(
    items: Iterable[dict[str, object]],
    *,
    min_score: float | None,
    max_score: float | None,
    class_ids: set[int] | None,
    class_names: set[str] | None,
    track_ids: set[str] | None,
    states: set[str] | None,
    min_area: int | None,
    max_area: int | None,
) -> list[dict[str, object]]:
    """按给定规则过滤 track item 列表。"""

    filtered_items: list[dict[str, object]] = []
    for item in items:
        score = float(item["score"])
        if min_score is not None and score < min_score:
            continue
        if max_score is not None and score > max_score:
            continue
        class_id = item.get("class_id")
        if class_ids is not None and class_id not in class_ids:
            continue
        class_name = item.get("class_name")
        if class_names is not None and class_name not in class_names:
            continue
        track_id = item.get("track_id")
        if track_ids is not None and track_id not in track_ids:
            continue
        state = item.get("state")
        if states is not None and state not in states:
            continue
        area = item.get("area")
        if min_area is not None:
            if isinstance(area, bool) or not isinstance(area, int) or area < min_area:
                continue
        if max_area is not None:
            if isinstance(area, bool) or not isinstance(area, int) or area > max_area:
                continue
        filtered_items.append(dict(item))
    return filtered_items


def _normalize_track_item(
    raw_item: object,
    *,
    node_id: str,
    field_name: str,
    item_index: int,
) -> dict[str, object]:
    """规范化单个 track item。"""

    if not isinstance(raw_item, dict):
        raise InvalidRequestError(
            f"{field_name}.items 的每一项都必须是对象",
            details={"node_id": node_id, "item_index": item_index},
        )
    track_id = raw_item.get("track_id")
    frame_index = raw_item.get("frame_index")
    score = raw_item.get("score")
    timestamp_ms = raw_item.get("timestamp_ms", 0.0)
    if not isinstance(track_id, str) or not track_id.strip():
        raise InvalidRequestError(
            f"{field_name}.items.track_id 必须是非空字符串",
            details={"node_id": node_id, "item_index": item_index, "track_id": track_id},
        )
    if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
        raise InvalidRequestError(
            f"{field_name}.items.frame_index 必须是非负整数",
            details={"node_id": node_id, "item_index": item_index, "frame_index": frame_index},
        )
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise InvalidRequestError(
            f"{field_name}.items.score 必须是数值",
            details={"node_id": node_id, "item_index": item_index, "score": score},
        )
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, (int, float)) or float(timestamp_ms) < 0:
        raise InvalidRequestError(
            f"{field_name}.items.timestamp_ms 必须是非负数",
            details={"node_id": node_id, "item_index": item_index, "timestamp_ms": timestamp_ms},
        )

    normalized_item: dict[str, object] = {
        "track_id": track_id.strip(),
        "frame_index": frame_index,
        "timestamp_ms": float(timestamp_ms),
        "score": float(score),
    }
    if "class_id" in raw_item:
        class_id = raw_item.get("class_id")
        if isinstance(class_id, bool) or not isinstance(class_id, int):
            raise InvalidRequestError(
                f"{field_name}.items.class_id 必须是整数",
                details={"node_id": node_id, "item_index": item_index, "class_id": class_id},
            )
        normalized_item["class_id"] = class_id
    if "class_name" in raw_item:
        class_name = raw_item.get("class_name")
        if not isinstance(class_name, str):
            raise InvalidRequestError(
                f"{field_name}.items.class_name 必须是字符串",
                details={"node_id": node_id, "item_index": item_index, "class_name": class_name},
            )
        normalized_item["class_name"] = class_name
    if "bbox_xyxy" in raw_item:
        normalized_item["bbox_xyxy"] = _normalize_bbox(raw_item.get("bbox_xyxy"), node_id=node_id, item_index=item_index)
    if "polygon_xy" in raw_item:
        normalized_item["polygon_xy"] = _normalize_polygon(raw_item.get("polygon_xy"), node_id=node_id, item_index=item_index)
    if "mask_image" in raw_item and raw_item.get("mask_image") is not None:
        try:
            normalized_item["mask_image"] = require_image_payload(raw_item.get("mask_image"))
        except InvalidRequestError as exc:
            raise InvalidRequestError(
                f"{field_name}.items.mask_image 必须是有效 image-ref",
                details={"node_id": node_id, "item_index": item_index, **(exc.details or {})},
            ) from exc
    if "region_id" in raw_item and raw_item.get("region_id") is not None:
        normalized_item["region_id"] = str(raw_item["region_id"])
    if "state" in raw_item and raw_item.get("state") is not None:
        normalized_item["state"] = str(raw_item["state"])
    if "prompt_id" in raw_item and raw_item.get("prompt_id") is not None:
        normalized_item["prompt_id"] = str(raw_item["prompt_id"])
    if "area" in raw_item:
        area = raw_item.get("area")
        if isinstance(area, bool) or not isinstance(area, int) or area < 0:
            raise InvalidRequestError(
                f"{field_name}.items.area 必须是非负整数",
                details={"node_id": node_id, "item_index": item_index, "area": area},
            )
        normalized_item["area"] = area
    for list_field_name in ("source_prompt_positive_texts", "source_prompt_negative_texts"):
        if list_field_name in raw_item:
            normalized_item[list_field_name] = _normalize_string_list(
                raw_item.get(list_field_name),
                node_id=node_id,
                item_index=item_index,
                field_name=list_field_name,
            )
    if "source_prompt_text" in raw_item and raw_item.get("source_prompt_text") is not None:
        normalized_item["source_prompt_text"] = str(raw_item["source_prompt_text"])
    return normalized_item


def _normalize_region_item(
    raw_item: object,
    *,
    node_id: str,
    field_name: str,
    item_index: int,
) -> dict[str, object]:
    """规范化单个 region item。"""

    if not isinstance(raw_item, dict):
        raise InvalidRequestError(
            f"{field_name}.items 的每一项都必须是对象",
            details={"node_id": node_id, "item_index": item_index},
        )
    region_id = raw_item.get("region_id")
    score = raw_item.get("score")
    if not isinstance(region_id, str) or not region_id.strip():
        raise InvalidRequestError(
            f"{field_name}.items.region_id 必须是非空字符串",
            details={"node_id": node_id, "item_index": item_index, "region_id": region_id},
        )
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise InvalidRequestError(
            f"{field_name}.items.score 必须是数值",
            details={"node_id": node_id, "item_index": item_index, "score": score},
        )
    area = raw_item.get("area")
    if isinstance(area, bool) or not isinstance(area, int) or area < 0:
        raise InvalidRequestError(
            f"{field_name}.items.area 必须是非负整数",
            details={"node_id": node_id, "item_index": item_index, "area": area},
        )
    normalized_item: dict[str, object] = {
        "region_id": region_id.strip(),
        "score": float(score),
        "class_id": int(raw_item.get("class_id", 0)) if isinstance(raw_item.get("class_id"), int) else 0,
        "class_name": str(raw_item.get("class_name") or ""),
        "bbox_xyxy": _normalize_bbox(raw_item.get("bbox_xyxy"), node_id=node_id, item_index=item_index),
        "polygon_xy": _normalize_polygon(raw_item.get("polygon_xy"), node_id=node_id, item_index=item_index),
        "area": area,
    }
    if "mask_image" in raw_item and raw_item.get("mask_image") is not None:
        try:
            normalized_item["mask_image"] = require_image_payload(raw_item.get("mask_image"))
        except InvalidRequestError as exc:
            raise InvalidRequestError(
                f"{field_name}.items.mask_image 必须是有效 image-ref",
                details={"node_id": node_id, "item_index": item_index, **(exc.details or {})},
            ) from exc
    for optional_int_field in ("frame_index",):
        if optional_int_field in raw_item and raw_item.get(optional_int_field) is not None:
            optional_value = raw_item.get(optional_int_field)
            if isinstance(optional_value, bool) or not isinstance(optional_value, int) or optional_value < 0:
                raise InvalidRequestError(
                    f"{field_name}.items.{optional_int_field} 必须是非负整数",
                    details={"node_id": node_id, "item_index": item_index, optional_int_field: optional_value},
                )
            normalized_item[optional_int_field] = optional_value
    for optional_number_field in ("timestamp_ms",):
        if optional_number_field in raw_item and raw_item.get(optional_number_field) is not None:
            optional_value = raw_item.get(optional_number_field)
            if (
                isinstance(optional_value, bool)
                or not isinstance(optional_value, (int, float))
                or float(optional_value) < 0
            ):
                raise InvalidRequestError(
                    f"{field_name}.items.{optional_number_field} 必须是非负数",
                    details={"node_id": node_id, "item_index": item_index, optional_number_field: optional_value},
                )
            normalized_item[optional_number_field] = float(optional_value)
    for optional_text_field in ("prompt_id", "source_prompt_text", "track_id", "state"):
        if optional_text_field in raw_item and raw_item.get(optional_text_field) is not None:
            normalized_item[optional_text_field] = str(raw_item.get(optional_text_field))
    for list_field_name in ("source_prompt_positive_texts", "source_prompt_negative_texts"):
        if list_field_name in raw_item:
            normalized_item[list_field_name] = _normalize_string_list(
                raw_item.get(list_field_name),
                node_id=node_id,
                item_index=item_index,
                field_name=list_field_name,
            )
    return normalized_item


def _normalize_bbox(raw_value: object, *, node_id: str, item_index: int) -> list[float]:
    """规范化 bbox_xyxy。"""

    if not isinstance(raw_value, list) or len(raw_value) != 4:
        raise InvalidRequestError(
            "tracks item 的 bbox_xyxy 必须是长度为 4 的数组",
            details={"node_id": node_id, "item_index": item_index},
        )
    normalized_bbox: list[float] = []
    for point_index, point_value in enumerate(raw_value, start=1):
        if isinstance(point_value, bool) or not isinstance(point_value, (int, float)):
            raise InvalidRequestError(
                "tracks item 的 bbox_xyxy 必须全部是数值",
                details={"node_id": node_id, "item_index": item_index, "point_index": point_index},
            )
        normalized_bbox.append(float(point_value))
    return normalized_bbox


def _normalize_polygon(raw_value: object, *, node_id: str, item_index: int) -> list[list[float]]:
    """规范化 polygon_xy。"""

    if not isinstance(raw_value, list):
        raise InvalidRequestError(
            "tracks item 的 polygon_xy 必须是数组",
            details={"node_id": node_id, "item_index": item_index},
        )
    normalized_polygon: list[list[float]] = []
    for point_index, point_value in enumerate(raw_value, start=1):
        if not isinstance(point_value, list) or len(point_value) != 2:
            raise InvalidRequestError(
                "tracks item 的 polygon_xy 每个点必须是长度为 2 的数组",
                details={"node_id": node_id, "item_index": item_index, "point_index": point_index},
            )
        normalized_point: list[float] = []
        for coord_index, coord_value in enumerate(point_value, start=1):
            if isinstance(coord_value, bool) or not isinstance(coord_value, (int, float)):
                raise InvalidRequestError(
                    "tracks item 的 polygon_xy 坐标必须是数值",
                    details={
                        "node_id": node_id,
                        "item_index": item_index,
                        "point_index": point_index,
                        "coord_index": coord_index,
                    },
                )
            normalized_point.append(float(coord_value))
        normalized_polygon.append(normalized_point)
    return normalized_polygon


def _normalize_string_list(
    raw_value: object,
    *,
    node_id: str,
    item_index: int,
    field_name: str,
) -> list[str]:
    """规范化字符串数组字段。"""

    if not isinstance(raw_value, list):
        raise InvalidRequestError(
            f"tracks item 的 {field_name} 必须是字符串数组",
            details={"node_id": node_id, "item_index": item_index},
        )
    normalized_values: list[str] = []
    for value_index, item_value in enumerate(raw_value, start=1):
        if not isinstance(item_value, str):
            raise InvalidRequestError(
                f"tracks item 的 {field_name} 必须全部是字符串",
                details={
                    "node_id": node_id,
                    "item_index": item_index,
                    "value_index": value_index,
                },
            )
        normalized_values.append(item_value)
    return normalized_values
