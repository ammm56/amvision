"""OpenCV line payload 的通用几何计算。"""

from __future__ import annotations

import math

from backend.service.application.errors import InvalidRequestError


def line_intersection(
    first_line: dict[str, object],
    second_line: dict[str, object],
    *,
    parallel_epsilon: float = 1e-8,
) -> list[float]:
    """计算两条无限直线的交点，并明确拒绝平行或退化输入。"""

    first_start, first_end = _line_points(first_line)
    second_start, second_end = _line_points(second_line)
    first_dx = first_end[0] - first_start[0]
    first_dy = first_end[1] - first_start[1]
    second_dx = second_end[0] - second_start[0]
    second_dy = second_end[1] - second_start[1]
    denominator = first_dx * second_dy - first_dy * second_dx
    length_product = math.hypot(first_dx, first_dy) * math.hypot(second_dx, second_dy)
    if length_product <= parallel_epsilon:
        raise InvalidRequestError("Line Intersection 不能处理长度为 0 的直线")
    if abs(denominator) / length_product <= parallel_epsilon:
        raise InvalidRequestError("Line Intersection 的两条直线平行或近似平行")
    delta_x = second_start[0] - first_start[0]
    delta_y = second_start[1] - first_start[1]
    first_parameter = (delta_x * second_dy - delta_y * second_dx) / denominator
    return [
        round(first_start[0] + first_parameter * first_dx, 4),
        round(first_start[1] + first_parameter * first_dy, 4),
    ]


def deduplicate_lines(
    line_items: list[dict[str, object]],
    *,
    angle_tolerance_deg: float,
    distance_tolerance_pixels: float,
) -> list[dict[str, object]]:
    """按输入顺序保留代表线段，过滤同一物理直线的重复片段。"""

    if angle_tolerance_deg < 0 or angle_tolerance_deg > 90:
        raise InvalidRequestError("angle_tolerance_deg 必须在 0 到 90 之间")
    if distance_tolerance_pixels < 0:
        raise InvalidRequestError("distance_tolerance_pixels 不能小于 0")
    result: list[dict[str, object]] = []
    for line_item in line_items:
        if any(
            _lines_are_duplicates(
                line_item,
                current_item,
                angle_tolerance_deg=angle_tolerance_deg,
                distance_tolerance_pixels=distance_tolerance_pixels,
            )
            for current_item in result
        ):
            continue
        result.append(dict(line_item))
    for line_index, line_item in enumerate(result, start=1):
        line_item["line_index"] = line_index
    return result


def select_line(lines: list[dict[str, object]], *, one_based_index: int, field_name: str) -> dict[str, object]:
    """按一基序号选择直线，禁止隐式使用第一条结果。"""

    if one_based_index < 1:
        raise InvalidRequestError(f"{field_name} 必须是正整数")
    if one_based_index > len(lines):
        raise InvalidRequestError(
            f"{field_name} 超出 line 数量",
            details={"selected_index": one_based_index, "count": len(lines)},
        )
    return dict(lines[one_based_index - 1])


def _lines_are_duplicates(
    candidate: dict[str, object],
    existing: dict[str, object],
    *,
    angle_tolerance_deg: float,
    distance_tolerance_pixels: float,
) -> bool:
    """判断两条线段是否描述同一条物理直线。"""

    candidate_angle = float(candidate["angle_deg"])
    if _angle_distance_deg(candidate_angle, float(existing["angle_deg"])) > angle_tolerance_deg:
        return False
    angle_radians = math.radians(candidate_angle)
    unit_x = math.cos(angle_radians)
    unit_y = math.sin(angle_radians)
    normal_x = -unit_y
    normal_y = unit_x
    candidate_midpoint = _line_midpoint(candidate)
    existing_midpoint = _line_midpoint(existing)
    normal_distance = abs(
        (candidate_midpoint[0] - existing_midpoint[0]) * normal_x
        + (candidate_midpoint[1] - existing_midpoint[1]) * normal_y
    )
    if normal_distance > distance_tolerance_pixels:
        return False
    candidate_start, candidate_end = _projection_interval(candidate, unit_x=unit_x, unit_y=unit_y)
    existing_start, existing_end = _projection_interval(existing, unit_x=unit_x, unit_y=unit_y)
    interval_gap = max(candidate_start, existing_start) - min(candidate_end, existing_end)
    return interval_gap <= distance_tolerance_pixels


def _line_points(line_item: dict[str, object]) -> tuple[list[float], list[float]]:
    """读取规范 lines.v1 item 的两个端点。"""

    start_xy = line_item.get("start_xy")
    end_xy = line_item.get("end_xy")
    if not isinstance(start_xy, list) or len(start_xy) != 2:
        raise InvalidRequestError("line.start_xy 必须包含两个坐标")
    if not isinstance(end_xy, list) or len(end_xy) != 2:
        raise InvalidRequestError("line.end_xy 必须包含两个坐标")
    return [float(start_xy[0]), float(start_xy[1])], [float(end_xy[0]), float(end_xy[1])]


def _line_midpoint(line_item: dict[str, object]) -> list[float]:
    """读取或计算线段中点。"""

    midpoint_xy = line_item.get("midpoint_xy")
    if isinstance(midpoint_xy, list) and len(midpoint_xy) == 2:
        return [float(midpoint_xy[0]), float(midpoint_xy[1])]
    start_xy, end_xy = _line_points(line_item)
    return [(start_xy[0] + end_xy[0]) / 2.0, (start_xy[1] + end_xy[1]) / 2.0]


def _angle_distance_deg(first_angle: float, second_angle: float) -> float:
    """计算无方向直线在 180 度周期内的最小角差。"""

    raw_distance = abs(first_angle - second_angle) % 180.0
    return min(raw_distance, 180.0 - raw_distance)


def _projection_interval(
    line_item: dict[str, object],
    *,
    unit_x: float,
    unit_y: float,
) -> tuple[float, float]:
    """把线段投影到指定方向并返回有序区间。"""

    start_xy, end_xy = _line_points(line_item)
    start_projection = start_xy[0] * unit_x + start_xy[1] * unit_y
    end_projection = end_xy[0] * unit_x + end_xy[1] * unit_y
    return min(start_projection, end_projection), max(start_projection, end_projection)
