"""Hough Circles 参数解析、排序和输出结构支持。"""

from __future__ import annotations

import math

from backend.nodes.parameter_utils import is_empty_parameter
from backend.service.application.errors import InvalidRequestError
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_float,
    require_non_negative_int,
)


def read_positive_float(raw_value: object, *, field_name: str, default_value: float) -> float:
    """读取正浮点参数。"""

    if is_empty_parameter(raw_value):
        return float(default_value)
    normalized_value = require_non_negative_float(raw_value, field_name=field_name)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return float(normalized_value)


def read_non_negative_int(raw_value: object, *, field_name: str, default_value: int) -> int:
    """读取非负整数参数。"""

    if is_empty_parameter(raw_value):
        return int(default_value)
    return int(require_non_negative_int(raw_value, field_name=field_name))


def normalize_sort_by(value: object) -> str:
    """规范化 Hough Circles 排序字段。"""

    if not isinstance(value, str) or not value.strip():
        return "quality_score"
    normalized_value = value.strip().lower()
    if normalized_value not in {
        "circle_index",
        "radius",
        "diameter",
        "area",
        "center_x",
        "center_y",
        "search_center_distance",
        "reference_center_distance",
        "reference_radius_deviation",
        "quality_score",
    }:
        raise InvalidRequestError("sort_by 不在支持的 Hough Circles 排序字段列表中")
    return normalized_value


def read_choice(raw_value: object, *, field_name: str, default_value: str, choices: set[str]) -> str:
    """读取字符串枚举参数。"""

    if is_empty_parameter(raw_value):
        return default_value
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in choices:
        raise InvalidRequestError(f"{field_name} 仅支持 {', '.join(sorted(choices))}")
    return normalized_value


def read_optional_point(raw_value: object, *, field_name: str) -> list[float] | None:
    """读取可选二维点。"""

    if is_empty_parameter(raw_value):
        return None
    if not isinstance(raw_value, list) or len(raw_value) != 2:
        raise InvalidRequestError(f"{field_name} 必须是 [x, y]")
    point: list[float] = []
    for value in raw_value:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise InvalidRequestError(f"{field_name} 坐标必须是有限数值")
        point.append(float(value))
    return point


def build_circle_item(
    *,
    circle_index: int,
    center_x: float,
    center_y: float,
    radius: float,
    search_center_xy: tuple[float, float],
    reference_center_xy: list[float] | None,
    reference_radius_px: float | None,
    fit_metrics: dict[str, object],
) -> dict[str, object]:
    """构造带工业定位质量指标的 circles.v1 item。"""

    center_x = round(center_x, 4)
    center_y = round(center_y, 4)
    radius = round(radius, 4)
    reference_center_distance = (
        math.hypot(center_x - reference_center_xy[0], center_y - reference_center_xy[1])
        if reference_center_xy is not None
        else 0.0
    )
    reference_radius_deviation = (
        abs(radius - reference_radius_px) if reference_radius_px is not None else 0.0
    )
    arc_coverage = float(fit_metrics.get("arc_coverage", 0.0))
    fit_rmse_px = float(fit_metrics.get("fit_rmse_px", 0.0))
    quality_score = max(0.0, min(1.0, arc_coverage * (1.0 / (1.0 + fit_rmse_px))))
    diameter = radius * 2.0
    return {
        "circle_index": circle_index,
        "center_xy": [center_x, center_y],
        "center_x": center_x,
        "center_y": center_y,
        "radius": radius,
        "diameter": round(diameter, 4),
        "area": round(math.pi * radius * radius, 4),
        "circumference": round(2.0 * math.pi * radius, 4),
        "search_center_distance": round(
            math.hypot(center_x - search_center_xy[0], center_y - search_center_xy[1]),
            4,
        ),
        "reference_center_distance": round(reference_center_distance, 4),
        "reference_radius_deviation": round(reference_radius_deviation, 4),
        "quality_score": round(quality_score, 6),
        **fit_metrics,
        "bbox_xyxy": [
            round(center_x - radius, 4),
            round(center_y - radius, 4),
            round(center_x + radius, 4),
            round(center_y + radius, 4),
        ],
    }
