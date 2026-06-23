"""Hough Circles 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    build_circles_payload,
    load_image_matrix,
    require_non_negative_float,
    require_non_negative_int,
    require_opencv_imports,
    require_positive_int,
)


NODE_TYPE_ID = "custom.opencv.hough-circles"


def _read_positive_float(raw_value: object, *, field_name: str, default_value: float) -> float:
    """读取正浮点参数。"""

    if raw_value in {None, ""}:
        return float(default_value)
    normalized_value = require_non_negative_float(raw_value, field_name=field_name)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return float(normalized_value)


def _read_non_negative_int(raw_value: object, *, field_name: str, default_value: int) -> int:
    """读取非负整数参数。"""

    if raw_value in {None, ""}:
        return int(default_value)
    return int(require_non_negative_int(raw_value, field_name=field_name))


def _read_optional_limit(raw_value: object) -> int | None:
    """读取可选 limit。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name="limit")


def _normalize_sort_by(value: object) -> str:
    """规范化 hough-circles 的排序字段。"""

    if not isinstance(value, str) or not value.strip():
        return "radius"
    normalized_value = value.strip().lower()
    if normalized_value not in {
        "circle_index",
        "radius",
        "diameter",
        "area",
        "center_x",
        "center_y",
    }:
        raise InvalidRequestError("sort_by 不在支持的 hough-circles 排序字段列表中")
    return normalized_value


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 Hough 圆检测。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, source_object_key, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    dp = _read_positive_float(request.parameters.get("dp"), field_name="dp", default_value=1.0)
    min_dist = _read_positive_float(
        request.parameters.get("min_dist"),
        field_name="min_dist",
        default_value=20.0,
    )
    param1 = _read_positive_float(
        request.parameters.get("param1"),
        field_name="param1",
        default_value=100.0,
    )
    param2 = _read_positive_float(
        request.parameters.get("param2"),
        field_name="param2",
        default_value=20.0,
    )
    min_radius = _read_non_negative_int(
        request.parameters.get("min_radius"),
        field_name="min_radius",
        default_value=0,
    )
    max_radius = _read_non_negative_int(
        request.parameters.get("max_radius"),
        field_name="max_radius",
        default_value=0,
    )
    if max_radius > 0 and max_radius < min_radius:
        raise InvalidRequestError("max_radius 不能小于 min_radius")
    sort_by = _normalize_sort_by(request.parameters.get("sort_by"))
    descending = bool(request.parameters.get("descending", True))
    limit = _read_optional_limit(request.parameters.get("limit"))

    raw_circles = cv2_module.HoughCircles(
        image_matrix,
        method=cv2_module.HOUGH_GRADIENT,
        dp=dp,
        minDist=min_dist,
        param1=param1,
        param2=param2,
        minRadius=min_radius,
        maxRadius=max_radius,
    )
    circle_items: list[dict[str, object]] = []
    if raw_circles is not None:
        for circle_index, raw_circle in enumerate(raw_circles[0], start=1):
            center_x = round(float(raw_circle[0]), 4)
            center_y = round(float(raw_circle[1]), 4)
            radius = round(float(raw_circle[2]), 4)
            diameter = round(float(radius * 2.0), 4)
            area = round(float(math.pi * radius * radius), 4)
            circumference = round(float(2.0 * math.pi * radius), 4)
            circle_items.append(
                {
                    "circle_index": int(circle_index),
                    "center_xy": [center_x, center_y],
                    "center_x": center_x,
                    "center_y": center_y,
                    "radius": radius,
                    "diameter": diameter,
                    "area": area,
                    "circumference": circumference,
                    "bbox_xyxy": [
                        round(center_x - radius, 4),
                        round(center_y - radius, 4),
                        round(center_x + radius, 4),
                        round(center_y + radius, 4),
                    ],
                }
            )

    circle_items.sort(key=lambda current_item: current_item[sort_by], reverse=descending)
    if limit is not None:
        circle_items = circle_items[:limit]

    return {
        "circles": build_circles_payload(
            items=circle_items,
            source_image=image_payload,
            source_object_key=source_object_key,
        ),
        "summary": build_value_payload(
            {
                "count": len(circle_items),
                "sort_by": sort_by,
                "descending": descending,
                "limit": limit,
                "dp": dp,
                "min_dist": min_dist,
                "param1": param1,
                "param2": param2,
                "min_radius": min_radius,
                "max_radius": max_radius,
                "max_radius_detected": round(
                    max((float(item["radius"]) for item in circle_items), default=0.0),
                    4,
                ),
                "mean_radius_detected": round(
                    (
                        sum(float(item["radius"]) for item in circle_items) / len(circle_items)
                        if circle_items
                        else 0.0
                    ),
                    4,
                ),
            }
        ),
    }
