"""ROI 几何规范化和面积计算。"""

from __future__ import annotations

import cv2
import numpy as np

from backend.service.application.errors import InvalidRequestError


def normalize_bbox_xyxy(
    raw_value: object,
    *,
    field_name: str,
    node_id: str | None,
) -> list[float]:
    """规范化 bbox_xyxy。"""

    if not isinstance(raw_value, list) or len(raw_value) != 4:
        raise InvalidRequestError(f"{field_name} 必须是长度为 4 的数值数组", details={"node_id": node_id})
    normalized_values: list[float] = []
    for item_value in raw_value:
        if isinstance(item_value, bool) or not isinstance(item_value, (int, float)):
            raise InvalidRequestError(f"{field_name} 必须全部是数值", details={"node_id": node_id})
        normalized_values.append(float(item_value))
    x1_value, y1_value, x2_value, y2_value = normalized_values
    if x2_value < x1_value or y2_value < y1_value:
        raise InvalidRequestError(f"{field_name} 要求 x2>=x1 且 y2>=y1", details={"node_id": node_id})
    return normalized_values


def normalize_polygon_xy(
    raw_value: object,
    *,
    field_name: str,
    node_id: str | None,
) -> list[list[float]]:
    """规范化 polygon_xy。"""

    if not isinstance(raw_value, list) or len(raw_value) < 3:
        raise InvalidRequestError(f"{field_name} 必须是至少 3 个点的数组", details={"node_id": node_id})
    normalized_points: list[list[float]] = []
    for point_value in raw_value:
        if not isinstance(point_value, list) or len(point_value) != 2:
            raise InvalidRequestError(f"{field_name} 中的点必须是长度为 2 的数组", details={"node_id": node_id})
        x_value, y_value = point_value
        if (
            isinstance(x_value, bool)
            or isinstance(y_value, bool)
            or not isinstance(x_value, (int, float))
            or not isinstance(y_value, (int, float))
        ):
            raise InvalidRequestError(f"{field_name} 中的点坐标必须是数值", details={"node_id": node_id})
        normalized_points.append([float(x_value), float(y_value)])
    return normalized_points


def polygon_bbox_xyxy(polygon_xy: list[list[float]]) -> list[float]:
    """根据 polygon 计算外接 bbox。"""

    x_values = [float(point[0]) for point in polygon_xy]
    y_values = [float(point[1]) for point in polygon_xy]
    return [min(x_values), min(y_values), max(x_values), max(y_values)]


def polygon_area(polygon_xy: list[list[float]]) -> int:
    """计算 polygon 面积。"""

    polygon_array = np.array(polygon_xy, dtype=np.float32)
    return max(0, int(round(abs(float(cv2.contourArea(polygon_array))))))


def bbox_area(bbox_xyxy: list[float]) -> int:
    """计算 bbox 面积。"""

    x1_value, y1_value, x2_value, y2_value = bbox_xyxy
    return max(0, int(round(max(0.0, x2_value - x1_value) * max(0.0, y2_value - y1_value))))


def bbox_to_polygon_xy(bbox_xyxy: list[float]) -> list[list[float]]:
    """把 bbox_xyxy 转成矩形 polygon。"""

    x1_value, y1_value, x2_value, y2_value = bbox_xyxy
    return [
        [x1_value, y1_value],
        [x2_value, y1_value],
        [x2_value, y2_value],
        [x1_value, y2_value],
    ]

