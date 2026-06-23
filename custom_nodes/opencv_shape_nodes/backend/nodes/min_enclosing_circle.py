"""Min Enclosing Circle 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    build_circles_payload,
    compute_contour_metrics_from_points,
    require_contours_payload,
    require_opencv_imports,
    require_positive_int,
)


NODE_TYPE_ID = "custom.opencv.min-enclosing-circle"


def _read_optional_limit(raw_value: object) -> int | None:
    """读取可选 limit。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name="limit")


def _normalize_sort_by(value: object) -> str:
    """规范化 min-enclosing-circle 的排序字段。"""

    if not isinstance(value, str) or not value.strip():
        return "radius"
    normalized_value = value.strip().lower()
    if normalized_value not in {
        "circle_index",
        "contour_index",
        "radius",
        "diameter",
        "area",
        "fill_ratio",
        "center_x",
        "center_y",
    }:
        raise InvalidRequestError("sort_by 不在支持的 min-enclosing-circle 排序字段列表中")
    return normalized_value


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对 contour 集合计算最小外接圆。"""

    cv2_module, np_module = require_opencv_imports()
    contours_payload = require_contours_payload(request.input_values.get("contours"))
    sort_by = _normalize_sort_by(request.parameters.get("sort_by"))
    descending = bool(request.parameters.get("descending", True))
    limit = _read_optional_limit(request.parameters.get("limit"))

    circle_items: list[dict[str, object]] = []
    for circle_index, contour_item in enumerate(contours_payload["items"], start=1):
        point_array = np_module.array(contour_item["points"], dtype=np_module.float32)
        if point_array.shape[0] < 2:
            continue
        contour_metrics = compute_contour_metrics_from_points(
            points=contour_item["points"],
            cv2_module=cv2_module,
            np_module=np_module,
        )
        center_xy, radius_value = cv2_module.minEnclosingCircle(point_array)
        radius = round(float(radius_value), 4)
        diameter = round(float(radius * 2.0), 4)
        area = round(float(math.pi * radius * radius), 4)
        contour_area = round(float(contour_metrics["area"]), 4)
        fill_ratio = round(float(contour_area / area), 4) if area > 0 else 0.0
        center_x = round(float(center_xy[0]), 4)
        center_y = round(float(center_xy[1]), 4)
        circle_items.append(
            {
                "circle_index": int(circle_index),
                "contour_index": int(contour_item["contour_index"]),
                "point_count": int(contour_item["point_count"]),
                "center_xy": [center_x, center_y],
                "center_x": center_x,
                "center_y": center_y,
                "radius": radius,
                "diameter": diameter,
                "area": area,
                "circumference": round(float(2.0 * math.pi * radius), 4),
                "contour_area": contour_area,
                "fill_ratio": fill_ratio,
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
            source_image=contours_payload.get("source_image"),
            source_object_key=contours_payload.get("source_object_key")
            if isinstance(contours_payload.get("source_object_key"), str)
            else None,
        ),
        "summary": build_value_payload(
            {
                "count": len(circle_items),
                "sort_by": sort_by,
                "descending": descending,
                "limit": limit,
                "max_radius": round(
                    max((float(item["radius"]) for item in circle_items), default=0.0),
                    4,
                ),
                "mean_radius": round(
                    (
                        sum(float(item["radius"]) for item in circle_items) / len(circle_items)
                        if circle_items
                        else 0.0
                    ),
                    4,
                ),
                "mean_fill_ratio": round(
                    (
                        sum(float(item["fill_ratio"]) for item in circle_items) / len(circle_items)
                        if circle_items
                        else 0.0
                    ),
                    4,
                ),
            }
        ),
    }
