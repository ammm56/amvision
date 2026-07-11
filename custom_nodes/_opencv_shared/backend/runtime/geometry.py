"""OpenCV shared 几何、点线圆和 contour 度量工具。"""

from __future__ import annotations

import math
from typing import Any

from backend.service.application.errors import InvalidRequestError
from custom_nodes._opencv_shared.backend.runtime.validators import require_number

def select_line_item(
    items: list[dict[str, object]],
    *,
    strategy: str,
    line_index: int | None,
) -> dict[str, object]:
    """按策略选择一条 line item。"""

    if not items:
        raise InvalidRequestError("lines payload 不能为空")
    if strategy == "first":
        return dict(items[0])
    if strategy == "longest":
        return dict(max(items, key=lambda item: float(item["length_pixels"])))
    if strategy == "shortest":
        return dict(min(items, key=lambda item: float(item["length_pixels"])))
    if strategy == "line-index":
        if line_index is None:
            raise InvalidRequestError("line_strategy 为 line-index 时必须提供 line_index")
        for item in items:
            if int(item["line_index"]) == line_index:
                return dict(item)
        raise InvalidRequestError("指定的 line_index 不存在", details={"line_index": line_index})
    raise InvalidRequestError("line_strategy 不在支持的列表中")

def select_circle_item(
    items: list[dict[str, object]],
    *,
    strategy: str,
    circle_index: int | None,
) -> dict[str, object]:
    """按策略选择一条 circle item。"""

    if not items:
        raise InvalidRequestError("circles payload 不能为空")
    if strategy == "first":
        return dict(items[0])
    if strategy == "largest":
        return dict(max(items, key=lambda item: float(item["radius"])))
    if strategy == "smallest":
        return dict(min(items, key=lambda item: float(item["radius"])))
    if strategy == "circle-index":
        if circle_index is None:
            raise InvalidRequestError("circle_strategy 为 circle-index 时必须提供 circle_index")
        for item in items:
            if int(item["circle_index"]) == circle_index:
                return dict(item)
        raise InvalidRequestError("指定的 circle_index 不存在", details={"circle_index": circle_index})
    raise InvalidRequestError("circle_strategy 不在支持的列表中")

def normalize_line_angle_deg(angle_deg: object) -> float:
    """把直线方向角规整到 [-90, 90) 区间。"""

    angle_value = require_number(angle_deg, field_name="angle_deg")
    normalized_value = float(angle_value % 180.0)
    if normalized_value >= 90.0:
        normalized_value -= 180.0
    return normalized_value

def compute_line_angle_delta_deg(*, angle_a_deg: object, angle_b_deg: object) -> float:
    """计算两条无方向直线之间的最小夹角差。"""

    normalized_a = normalize_line_angle_deg(angle_a_deg)
    normalized_b = normalize_line_angle_deg(angle_b_deg)
    delta_value = float(normalized_b - normalized_a)
    while delta_value < -90.0:
        delta_value += 180.0
    while delta_value >= 90.0:
        delta_value -= 180.0
    return delta_value

def measure_point_distance(*, point_a_xy: tuple[float, float], point_b_xy: tuple[float, float]) -> dict[str, float]:
    """计算两点之间的欧氏距离和坐标差。"""

    point_a_x, point_a_y = point_a_xy
    point_b_x, point_b_y = point_b_xy
    dx_pixels = float(point_b_x - point_a_x)
    dy_pixels = float(point_b_y - point_a_y)
    distance_pixels = float(math.hypot(dx_pixels, dy_pixels))
    manhattan_distance_pixels = float(abs(dx_pixels) + abs(dy_pixels))
    midpoint_x = float((point_a_x + point_b_x) / 2.0)
    midpoint_y = float((point_a_y + point_b_y) / 2.0)
    return {
        "dx_pixels": dx_pixels,
        "dy_pixels": dy_pixels,
        "distance_pixels": distance_pixels,
        "manhattan_distance_pixels": manhattan_distance_pixels,
        "midpoint_x": midpoint_x,
        "midpoint_y": midpoint_y,
    }

def measure_point_to_line(*, point_xy: tuple[float, float], line_item: dict[str, object]) -> dict[str, float]:
    """计算单点到无限延长直线的投影和距离。"""

    point_x, point_y = point_xy
    start_x, start_y = normalize_point_xy(line_item.get("start_xy"), field_name="start_xy")
    end_x, end_y = normalize_point_xy(line_item.get("end_xy"), field_name="end_xy")
    line_dx = float(end_x - start_x)
    line_dy = float(end_y - start_y)
    line_length_pixels = float(math.hypot(line_dx, line_dy))
    if line_length_pixels <= 0:
        raise InvalidRequestError("选中的 line 长度必须大于 0")
    relative_dx = float(point_x - start_x)
    relative_dy = float(point_y - start_y)
    signed_distance_pixels = float((relative_dx * line_dy - relative_dy * line_dx) / line_length_pixels)
    distance_pixels = float(abs(signed_distance_pixels))
    projection_ratio = float((relative_dx * line_dx + relative_dy * line_dy) / (line_length_pixels * line_length_pixels))
    projection_x = float(start_x + projection_ratio * line_dx)
    projection_y = float(start_y + projection_ratio * line_dy)
    return {
        "distance_pixels": distance_pixels,
        "signed_distance_pixels": signed_distance_pixels,
        "projection_ratio": projection_ratio,
        "projection_x": projection_x,
        "projection_y": projection_y,
        "line_length_pixels": line_length_pixels,
        "line_dx": line_dx,
        "line_dy": line_dy,
    }

def extract_point_from_value(raw_value: object, *, field_name: str) -> tuple[float, float]:
    """从常见 value.v1 形状中解析单个点坐标。"""

    if isinstance(raw_value, (list, tuple)):
        return normalize_point_xy(raw_value, field_name=field_name)
    if isinstance(raw_value, dict):
        if "point_xy" in raw_value:
            return normalize_point_xy(raw_value.get("point_xy"), field_name=f"{field_name}.point_xy")
        if "center_xy" in raw_value:
            return normalize_point_xy(raw_value.get("center_xy"), field_name=f"{field_name}.center_xy")
        if "midpoint_xy" in raw_value:
            return normalize_point_xy(raw_value.get("midpoint_xy"), field_name=f"{field_name}.midpoint_xy")
        if "x" in raw_value and "y" in raw_value:
            point_x = require_number(raw_value.get("x"), field_name=f"{field_name}.x")
            point_y = require_number(raw_value.get("y"), field_name=f"{field_name}.y")
            return point_x, point_y
    raise InvalidRequestError(
        f"{field_name} 输入必须是 [x, y]、{{point_xy:[x,y]}}、{{center_xy:[x,y]}}、{{midpoint_xy:[x,y]}} 或 {{x, y}}"
    )

def normalize_bbox(raw_bbox: object) -> tuple[int, int, int, int]:
    """把 detection bbox 规范化为 OpenCV 可用的整数坐标。

    参数：
    - raw_bbox：原始 bbox 数据。

    返回：
    - tuple[int, int, int, int]：规范化后的 xyxy 整数坐标。
    """

    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) < 4:
        raise InvalidRequestError("bbox_xyxy 至少包含四个坐标")
    x1, y1, x2, y2 = raw_bbox[:4]
    return int(round(float(x1))), int(round(float(y1))), int(round(float(x2))), int(round(float(y2)))

def normalize_bbox_number(raw_bbox: object, *, field_name: str) -> tuple[float, float, float, float]:
    """把 bbox 规范化为数值 xyxy 坐标。"""

    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) < 4:
        raise InvalidRequestError(f"{field_name} 至少包含四个坐标")
    x1_value = require_number(raw_bbox[0], field_name=f"{field_name}[0]")
    y1_value = require_number(raw_bbox[1], field_name=f"{field_name}[1]")
    x2_value = require_number(raw_bbox[2], field_name=f"{field_name}[2]")
    y2_value = require_number(raw_bbox[3], field_name=f"{field_name}[3]")
    return x1_value, y1_value, x2_value, y2_value

def normalize_point_xy(raw_value: object, *, field_name: str) -> tuple[float, float]:
    """把点坐标规范化为数值 x/y。"""

    if not isinstance(raw_value, (list, tuple)) or len(raw_value) < 2:
        raise InvalidRequestError(f"{field_name} 必须包含两个坐标")
    point_x = require_number(raw_value[0], field_name=f"{field_name}[0]")
    point_y = require_number(raw_value[1], field_name=f"{field_name}[1]")
    return point_x, point_y

def contour_points_to_matrix(*, points: list[list[int]], np_module: Any):
    """把 contour 点集转换为 OpenCV contour matrix。"""

    if not points:
        raise InvalidRequestError("contour.points 不能为空")
    return np_module.array(points, dtype=np_module.int32).reshape((-1, 1, 2))

def compute_contour_metrics_from_points(
    *,
    points: list[list[int]],
    cv2_module: Any,
    np_module: Any,
) -> dict[str, object]:
    """根据 contour 点集计算面积、bbox、周长等基础度量。"""

    contour_matrix = contour_points_to_matrix(points=points, np_module=np_module)
    bbox_x, bbox_y, bbox_width, bbox_height = cv2_module.boundingRect(contour_matrix)
    bbox_xyxy = [
        int(bbox_x),
        int(bbox_y),
        int(bbox_x + bbox_width),
        int(bbox_y + bbox_height),
    ]
    area = round(float(cv2_module.contourArea(contour_matrix)), 4)
    perimeter = round(float(cv2_module.arcLength(contour_matrix, True)), 4)
    center_x = round((float(bbox_xyxy[0]) + float(bbox_xyxy[2])) / 2.0, 4)
    center_y = round((float(bbox_xyxy[1]) + float(bbox_xyxy[3])) / 2.0, 4)
    aspect_ratio = round(float(bbox_width / bbox_height), 4) if bbox_height > 0 else 0.0
    return {
        "bbox_xyxy": bbox_xyxy,
        "width": int(bbox_width),
        "height": int(bbox_height),
        "area": area,
        "perimeter": perimeter,
        "center_xy": [center_x, center_y],
        "aspect_ratio": aspect_ratio,
    }

def build_contour_item_from_cv_contour(
    *,
    contour: Any,
    contour_index: int,
    cv2_module: Any,
    np_module: Any,
) -> dict[str, object] | None:
    """把 OpenCV contour 转为结构化 contour item。"""

    point_pairs = contour.reshape(-1, 2)
    contour_points = [[int(point_x), int(point_y)] for point_x, point_y in point_pairs.tolist()]
    if len(contour_points) < 3:
        return None
    contour_metrics = compute_contour_metrics_from_points(
        points=contour_points,
        cv2_module=cv2_module,
        np_module=np_module,
    )
    return {
        "contour_index": int(contour_index),
        "point_count": len(contour_points),
        "bbox_xyxy": list(contour_metrics["bbox_xyxy"]),
        "points": contour_points,
        "width": int(contour_metrics["width"]),
        "height": int(contour_metrics["height"]),
        "area": float(contour_metrics["area"]),
        "perimeter": float(contour_metrics["perimeter"]),
        "center_xy": list(contour_metrics["center_xy"]),
        "aspect_ratio": float(contour_metrics["aspect_ratio"]),
    }
