"""Barcode/QR 结果筛选与匹配工具。"""

from __future__ import annotations

import re

from backend.service.application.errors import InvalidRequestError
from custom_nodes.barcode_protocol_nodes.backend.runtime.results import (
    rebuild_barcode_results_payload,
    require_barcode_position_payload,
    require_barcode_results_payload,
)
from custom_nodes.barcode_protocol_nodes.backend.runtime.validators import read_optional_bool


def filter_barcode_results_payload(
    results_payload: object,
    *,
    parameters: dict[str, object] | None = None,
) -> dict[str, object]:
    """按参数条件筛选 barcode-results payload。

    参数：
    - results_payload：输入的 barcode-results.v1 payload。
    - parameters：筛选参数字典。

    返回：
    - dict[str, object]：筛选后的 barcode-results.v1 payload。
    """

    normalized_payload = require_barcode_results_payload(results_payload)
    normalized_parameters = parameters if isinstance(parameters, dict) else {}
    filtered_items = [
        item for item in normalized_payload["items"] if _barcode_item_matches_parameters(item, normalized_parameters)
    ]
    return rebuild_barcode_results_payload(normalized_payload, filtered_items)


def _barcode_item_matches_parameters(item: dict[str, object], parameters: dict[str, object]) -> bool:
    """判断单个条码结果项是否满足筛选条件。"""

    ignore_case = read_optional_bool(parameters.get("ignore_case"), default=True)
    if not _match_formats(item, parameters.get("formats"), ignore_case=ignore_case):
        return False
    if not _match_text(item, parameters, ignore_case=ignore_case):
        return False
    if not _match_index(item, parameters):
        return False
    if not _match_region(item, parameters):
        return False
    return True


def _match_formats(item: dict[str, object], raw_formats: object, *, ignore_case: bool) -> bool:
    """按 format 条件判断是否匹配。"""

    formats = _normalize_string_list(raw_formats, field_name="formats")
    if not formats:
        return True
    item_candidates = [item.get("format"), item.get("symbology")]
    normalized_candidates = {
        _normalize_match_text(candidate, ignore_case=ignore_case)
        for candidate in item_candidates
        if isinstance(candidate, str) and candidate.strip()
    }
    normalized_formats = {_normalize_match_text(value, ignore_case=ignore_case) for value in formats}
    return bool(normalized_candidates.intersection(normalized_formats))


def _match_text(item: dict[str, object], parameters: dict[str, object], *, ignore_case: bool) -> bool:
    """按 text 条件判断是否匹配。"""

    item_text = item.get("text")
    normalized_item_text = item_text if isinstance(item_text, str) else ""
    comparable_text = _normalize_match_text(normalized_item_text, ignore_case=ignore_case)

    text_equals = parameters.get("text_equals")
    if isinstance(text_equals, str) and text_equals.strip():
        if comparable_text != _normalize_match_text(text_equals, ignore_case=ignore_case):
            return False

    text_contains = parameters.get("text_contains")
    if isinstance(text_contains, str) and text_contains.strip():
        if _normalize_match_text(text_contains, ignore_case=ignore_case) not in comparable_text:
            return False

    text_regex = parameters.get("text_regex")
    if isinstance(text_regex, str) and text_regex.strip():
        regex_flags = re.IGNORECASE if ignore_case else 0
        if re.search(text_regex, normalized_item_text, flags=regex_flags) is None:
            return False

    return True


def _match_index(item: dict[str, object], parameters: dict[str, object]) -> bool:
    """按 index 条件判断是否匹配。"""

    item_index = int(item.get("index", 0))
    indices = _normalize_int_list(parameters.get("indices"), field_name="indices")
    if indices and item_index not in set(indices):
        return False

    min_index = parameters.get("min_index")
    if min_index is not None and item_index < int(min_index):
        return False

    max_index = parameters.get("max_index")
    if max_index is not None and item_index > int(max_index):
        return False
    return True


def _match_region(item: dict[str, object], parameters: dict[str, object]) -> bool:
    """按区域范围条件判断是否匹配。"""

    region_bounds = _normalize_region_bounds(parameters.get("region_bounds_xyxy"))
    if region_bounds is None:
        return True
    position_payload = require_barcode_position_payload(item.get("position"))
    item_bounds = _normalize_region_bounds(position_payload.get("bounds_xyxy"))
    if item_bounds is None:
        return False

    region_match_mode = parameters.get("region_match_mode", "intersects")
    if not isinstance(region_match_mode, str):
        raise InvalidRequestError("region_match_mode 必须是字符串")
    normalized_mode = region_match_mode.strip().lower()
    if normalized_mode == "intersects":
        return _bounds_intersect(item_bounds, region_bounds)
    if normalized_mode == "center-in":
        center_xy = position_payload.get("center_xy")
        if not isinstance(center_xy, list) or len(center_xy) < 2:
            return False
        return _point_in_bounds(float(center_xy[0]), float(center_xy[1]), region_bounds)
    if normalized_mode == "bounds-in":
        return _bounds_in_bounds(item_bounds, region_bounds)
    raise InvalidRequestError("region_match_mode 不受支持")


def _normalize_match_text(value: str, *, ignore_case: bool) -> str:
    """规范化匹配用文本。"""

    normalized_value = value.strip()
    return normalized_value.casefold() if ignore_case else normalized_value


def _normalize_string_list(value: object, *, field_name: str) -> list[str]:
    """把数组或逗号分隔字符串解析为字符串列表。"""

    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if not isinstance(value, list):
        raise InvalidRequestError(f"{field_name} 必须是数组或字符串")
    normalized_values: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise InvalidRequestError(f"{field_name} 中的每一项都必须是字符串")
        if item.strip():
            normalized_values.append(item.strip())
    return normalized_values


def _normalize_int_list(value: object, *, field_name: str) -> list[int]:
    """把数组或逗号分隔字符串解析为整数列表。"""

    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",") if item.strip()]
        return [int(item) for item in raw_items]
    if not isinstance(value, list):
        raise InvalidRequestError(f"{field_name} 必须是数组或字符串")
    return [int(item) for item in value]


def _normalize_region_bounds(value: object) -> list[int] | None:
    """把区域范围参数解析为 [x1, y1, x2, y2]。"""

    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        raise InvalidRequestError("region_bounds_xyxy 必须是长度为 4 的数组")
    x1, y1, x2, y2 = [int(round(float(item))) for item in value[:4]]
    return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]


def _bounds_intersect(bounds_a: list[int], bounds_b: list[int]) -> bool:
    """判断两个矩形范围是否相交。"""

    return not (
        bounds_a[2] < bounds_b[0]
        or bounds_a[0] > bounds_b[2]
        or bounds_a[3] < bounds_b[1]
        or bounds_a[1] > bounds_b[3]
    )


def _bounds_in_bounds(inner_bounds: list[int], outer_bounds: list[int]) -> bool:
    """判断一个矩形是否完全位于另一个矩形内部。"""

    return (
        inner_bounds[0] >= outer_bounds[0]
        and inner_bounds[1] >= outer_bounds[1]
        and inner_bounds[2] <= outer_bounds[2]
        and inner_bounds[3] <= outer_bounds[3]
    )


def _point_in_bounds(x_value: float, y_value: float, bounds: list[int]) -> bool:
    """判断点是否位于指定矩形范围内。"""

    return bounds[0] <= x_value <= bounds[2] and bounds[1] <= y_value <= bounds[3]
