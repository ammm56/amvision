"""tracks.v1 payload 构造与转换函数。"""

from __future__ import annotations

from collections.abc import Iterable

from backend.service.application.errors import InvalidRequestError


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

