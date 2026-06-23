"""tracks.v1 过滤函数。"""

from __future__ import annotations

from collections.abc import Iterable


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

