"""装配节点 region selector helper。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.assembly.geometry import compute_bbox_center
from backend.nodes.core_nodes.support.assembly.parameters import (
    read_optional_non_negative_int,
    read_optional_non_negative_number,
    read_optional_text,
)
from backend.nodes.core_nodes.support.region import filter_region_items
from backend.service.application.errors import InvalidRequestError


REGION_SELECTION_STRATEGY_ENUM = (
    "largest-area",
    "highest-score",
    "first",
    "leftmost",
    "rightmost",
    "topmost",
    "bottommost",
)
SUPPORTED_REGION_SELECTION_STRATEGIES = frozenset(REGION_SELECTION_STRATEGY_ENUM)


def read_region_selector(
    raw_value: object,
    *,
    node_name: str,
    field_name: str,
) -> dict[str, object]:
    """读取装配节点里的单侧 region selector。"""

    if not isinstance(raw_value, dict):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是对象")
    class_name = read_optional_text(
        raw_value.get("class_name"),
        field_name=f"{field_name}.class_name",
    )
    class_id = read_optional_non_negative_int(
        raw_value.get("class_id"),
        field_name=f"{field_name}.class_id",
    )
    prompt_id = read_optional_text(
        raw_value.get("prompt_id"),
        field_name=f"{field_name}.prompt_id",
    )
    track_id = read_optional_text(
        raw_value.get("track_id"),
        field_name=f"{field_name}.track_id",
    )
    state = read_optional_text(raw_value.get("state"), field_name=f"{field_name}.state")
    if class_name is None and class_id is None and prompt_id is None and track_id is None and state is None:
        raise InvalidRequestError(
            f"{node_name} 节点的 {field_name} 至少需要提供 class_name、class_id、prompt_id、track_id 或 state 之一"
        )
    min_score = read_optional_non_negative_number(
        raw_value.get("min_score"),
        field_name=f"{field_name}.min_score",
    )
    max_score = read_optional_non_negative_number(
        raw_value.get("max_score"),
        field_name=f"{field_name}.max_score",
    )
    min_area = read_optional_non_negative_int(
        raw_value.get("min_area"),
        field_name=f"{field_name}.min_area",
    )
    max_area = read_optional_non_negative_int(
        raw_value.get("max_area"),
        field_name=f"{field_name}.max_area",
    )
    if min_score is not None and max_score is not None and max_score < min_score:
        raise InvalidRequestError(f"{field_name}.max_score 不能小于 min_score")
    if min_area is not None and max_area is not None and max_area < min_area:
        raise InvalidRequestError(f"{field_name}.max_area 不能小于 min_area")
    return {
        "strategy": read_region_selection_strategy(
            raw_value.get("strategy"),
            field_name=f"{field_name}.strategy",
        ),
        "class_name": class_name,
        "class_id": class_id,
        "prompt_id": prompt_id,
        "track_id": track_id,
        "state": state,
        "min_score": min_score,
        "max_score": max_score,
        "min_area": min_area,
        "max_area": max_area,
    }


def read_region_selection_strategy(raw_value: object, *, field_name: str) -> str:
    """读取 region 选择策略。"""

    if raw_value is None:
        return "largest-area"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in SUPPORTED_REGION_SELECTION_STRATEGIES:
        raise InvalidRequestError(f"{field_name} 仅支持 largest-area、highest-score 或 first")
    return normalized_value


def select_region_candidates(
    items: list[dict[str, object]],
    *,
    selector: dict[str, object],
) -> list[dict[str, object]]:
    """按 selector 过滤候选区域。"""

    class_id = selector["class_id"]
    class_name = selector["class_name"]
    prompt_id = selector["prompt_id"]
    track_id = selector["track_id"]
    state = selector["state"]
    return filter_region_items(
        items,
        min_score=selector["min_score"],
        max_score=selector["max_score"],
        min_area=selector["min_area"],
        max_area=selector["max_area"],
        class_ids={class_id} if class_id is not None else None,
        class_names={class_name} if class_name is not None else None,
        prompt_ids={prompt_id} if prompt_id is not None else None,
        track_ids={track_id} if track_id is not None else None,
        states={state} if state is not None else None,
    )


def select_single_region_item(
    items: list[dict[str, object]],
    *,
    strategy: str,
) -> dict[str, object] | None:
    """按装配节点支持的策略挑选单个 region。"""

    normalized_items = list(items)
    if not normalized_items:
        return None
    if strategy == "first":
        return dict(normalized_items[0])
    if strategy == "largest-area":
        return dict(max(normalized_items, key=lambda item: (int(item["area"]), float(item["score"]))))
    if strategy == "highest-score":
        return dict(max(normalized_items, key=lambda item: (float(item["score"]), int(item["area"]))))
    if strategy == "leftmost":
        return dict(min(normalized_items, key=lambda item: (_compute_center_x(item), _compute_center_y(item))))
    if strategy == "rightmost":
        return dict(max(normalized_items, key=lambda item: (_compute_center_x(item), -_compute_center_y(item))))
    if strategy == "topmost":
        return dict(min(normalized_items, key=lambda item: (_compute_center_y(item), _compute_center_x(item))))
    if strategy == "bottommost":
        return dict(max(normalized_items, key=lambda item: (_compute_center_y(item), -_compute_center_x(item))))
    raise InvalidRequestError("不支持的装配节点 region 选择策略", details={"strategy": strategy})


def build_selector_summary(selector: dict[str, object]) -> dict[str, object]:
    """构造 selector 摘要。"""

    return {
        "strategy": selector["strategy"],
        "class_name": selector["class_name"],
        "class_id": selector["class_id"],
        "prompt_id": selector["prompt_id"],
        "track_id": selector["track_id"],
        "state": selector["state"],
        "min_score": selector["min_score"],
        "max_score": selector["max_score"],
        "min_area": selector["min_area"],
        "max_area": selector["max_area"],
    }


def _compute_center_x(item: dict[str, object]) -> float:
    """读取 region item 的中心 X。"""

    center_x, _center_y = compute_bbox_center(item.get("bbox_xyxy"), node_name="assembly-node-selector")
    return center_x


def _compute_center_y(item: dict[str, object]) -> float:
    """读取 region item 的中心 Y。"""

    _center_x, center_y = compute_bbox_center(item.get("bbox_xyxy"), node_name="assembly-node-selector")
    return center_y
