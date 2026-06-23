"""regions.v1 payload、筛选和统计支撑函数。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from statistics import median

from backend.service.application.errors import InvalidRequestError


def build_regions_payload(
    *,
    source_image: object,
    selected_frame_index: int | None,
    items: Iterable[dict[str, object]],
) -> dict[str, object]:
    """构建规范化后的 regions.v1 payload。"""

    normalized_items = [dict(item) for item in items]
    payload: dict[str, object] = {
        "count": len(normalized_items),
        "items": normalized_items,
    }
    if isinstance(source_image, dict):
        payload["source_image"] = dict(source_image)
    if selected_frame_index is not None:
        payload["selected_frame_index"] = int(selected_frame_index)
    return payload


def filter_region_items(
    items: Iterable[dict[str, object]],
    *,
    min_score: float | None,
    max_score: float | None,
    min_area: int | None,
    max_area: int | None,
    class_ids: set[int] | None,
    class_names: set[str] | None,
    prompt_ids: set[str] | None,
    track_ids: set[str] | None,
    states: set[str] | None,
) -> list[dict[str, object]]:
    """按给定规则过滤 region item 列表。"""

    filtered_items: list[dict[str, object]] = []
    for item in items:
        score = float(item["score"])
        if min_score is not None and score < min_score:
            continue
        if max_score is not None and score > max_score:
            continue
        area = int(item["area"])
        if min_area is not None and area < min_area:
            continue
        if max_area is not None and area > max_area:
            continue
        class_id = item.get("class_id")
        if class_ids is not None and class_id not in class_ids:
            continue
        class_name = item.get("class_name")
        if class_names is not None and class_name not in class_names:
            continue
        prompt_id = item.get("prompt_id")
        if prompt_ids is not None and prompt_id not in prompt_ids:
            continue
        track_id = item.get("track_id")
        if track_ids is not None and track_id not in track_ids:
            continue
        state = item.get("state")
        if states is not None and state not in states:
            continue
        filtered_items.append(dict(item))
    return filtered_items


def select_best_region_item(
    items: Iterable[dict[str, object]],
    *,
    strategy: str,
) -> dict[str, object] | None:
    """按策略挑选最优 region。"""

    normalized_items = list(items)
    if not normalized_items:
        return None
    if strategy == "first":
        return dict(normalized_items[0])
    if strategy == "largest-area":
        return dict(
            max(
                normalized_items,
                key=lambda item: (int(item["area"]), float(item["score"])),
            )
        )
    if strategy == "highest-score":
        return dict(
            max(
                normalized_items,
                key=lambda item: (float(item["score"]), int(item["area"])),
            )
        )
    raise InvalidRequestError(
        "不支持的 regions-select-best strategy",
        details={"strategy": strategy},
    )


def build_score_summary(items: Iterable[dict[str, object]]) -> dict[str, object]:
    """统计 region score 摘要。"""

    scores = [float(item["score"]) for item in items]
    if not scores:
        return {
            "count": 0,
            "min_score": None,
            "max_score": None,
            "avg_score": None,
            "median_score": None,
        }
    return {
        "count": len(scores),
        "min_score": min(scores),
        "max_score": max(scores),
        "avg_score": sum(scores) / len(scores),
        "median_score": float(median(scores)),
    }


def build_class_distribution(items: Iterable[dict[str, object]]) -> dict[str, int]:
    """统计类别名称分布。"""

    counter = Counter(str(item.get("class_name") or "") for item in items)
    return dict(sorted(counter.items(), key=lambda pair: pair[0]))


def read_optional_number(
    raw_value: object,
    *,
    field_name: str,
    node_name: str,
) -> float | None:
    """读取可选数值参数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是数值")
    return float(raw_value)


def read_optional_int(
    raw_value: object,
    *,
    field_name: str,
    node_name: str,
) -> int | None:
    """读取可选整数参数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是整数")
    return int(raw_value)


def read_optional_int_set(
    raw_value: object,
    *,
    field_name: str,
    node_name: str,
) -> set[int] | None:
    """读取可选整数集合参数。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, list):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是整数数组")
    normalized_values: set[int] = set()
    for item_index, item_value in enumerate(raw_value, start=1):
        if isinstance(item_value, bool) or not isinstance(item_value, int):
            raise InvalidRequestError(
                f"{node_name} 节点的 {field_name} 必须全部是整数",
                details={"field_name": field_name, "item_index": item_index},
            )
        normalized_values.add(int(item_value))
    return normalized_values


def read_optional_str_set(
    raw_value: object,
    *,
    field_name: str,
    node_name: str,
) -> set[str] | None:
    """读取可选字符串集合参数。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, list):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是字符串数组")
    normalized_values: set[str] = set()
    for item_index, item_value in enumerate(raw_value, start=1):
        if not isinstance(item_value, str):
            raise InvalidRequestError(
                f"{node_name} 节点的 {field_name} 必须全部是字符串",
                details={"field_name": field_name, "item_index": item_index},
            )
        normalized_values.add(item_value)
    return normalized_values

