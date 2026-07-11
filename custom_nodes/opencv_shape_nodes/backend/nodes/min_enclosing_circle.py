"""Min Enclosing Circle 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import build_debug_image_preview_output
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.payloads import (
    build_circles_payload,
    require_contours_payload,
)
from custom_nodes._opencv_shared.backend.runtime.geometry import compute_contour_metrics_from_points
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.validators import require_positive_int


NODE_TYPE_ID = "custom.opencv.min-enclosing-circle"


def _read_optional_limit(raw_value: object) -> int | None:
    """读取可选 limit。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name="limit")


def _read_optional_selected_contour_index(raw_value: object) -> int | None:
    """读取可选点选 contour 序号。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name="selected_contour_index")


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
    selected_contour_index = _read_optional_selected_contour_index(request.parameters.get("selected_contour_index"))

    circle_items: list[dict[str, object]] = []
    for contour_item in contours_payload["items"]:
        contour_index = int(contour_item["contour_index"])
        if selected_contour_index is not None and contour_index != selected_contour_index:
            continue
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
                "circle_index": len(circle_items) + 1,
                "contour_index": contour_index,
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
    for circle_index, circle_item in enumerate(circle_items, start=1):
        circle_item["circle_index"] = circle_index

    source_image = contours_payload.get("source_image")
    source_object_key = (
        contours_payload.get("source_object_key")
        if isinstance(contours_payload.get("source_object_key"), str)
        else None
    )
    outputs: dict[str, object] = {
        "circles": build_circles_payload(
            items=circle_items,
            source_image=source_image,
            source_object_key=source_object_key,
        ),
        "summary": build_value_payload(
            {
                "count": len(circle_items),
                "sort_by": sort_by,
                "descending": descending,
                "limit": limit,
                "selected_contour_index": selected_contour_index,
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
    if isinstance(source_image, dict):
        outputs.update(
            build_debug_image_preview_output(
                request,
                image_payload=source_image,
                title="Min Enclosing Circle",
                artifact_name="min-enclosing-circle-debug-preview",
                overlays=_build_circle_overlays(circle_items),
                interaction=_build_min_enclosing_circle_interaction(limit=limit),
            )
        )
    return outputs


def _build_min_enclosing_circle_interaction(*, limit: int | None) -> dict[str, object]:
    """声明 Min Enclosing Circle 在图片面板中的圆形结果点选能力。"""

    return {
        "mode": "edit",
        "coordinate_space": "source-image",
        "tools": [
            {
                "tool": "circle",
                "label": "圆点选",
                "target_parameters": ["selected_contour_index"],
            },
        ],
        "controls": [
            _build_numeric_control("limit", "Limit", limit or 20, min_value=1.0, max_value=200.0, step=1.0),
        ],
    }


def _build_numeric_control(
    parameter_name: str,
    label: str,
    value: float | int,
    *,
    min_value: float,
    max_value: float,
    step: float,
) -> dict[str, object]:
    """构造图片面板实时调参使用的数值控件声明。"""

    return {
        "parameter_name": parameter_name,
        "label": label,
        "control": "slider",
        "min": min_value,
        "max": max_value,
        "step": step,
        "value": value,
        "default_value": value,
    }


def _build_circle_overlays(circle_items: list[dict[str, object]]) -> list[dict[str, object]]:
    """把最小外接圆结果转换为图片面板 overlay。"""

    overlays: list[dict[str, object]] = []
    for circle_item in circle_items[:120]:
        center_xy = circle_item.get("center_xy")
        radius = circle_item.get("radius")
        if not isinstance(center_xy, list) or len(center_xy) < 2 or not isinstance(radius, (int, float)):
            continue
        circle_index = int(circle_item.get("circle_index", len(overlays) + 1))
        contour_index = int(circle_item.get("contour_index", circle_index))
        overlays.append(
            {
                "kind": "circle",
                "id": f"min-enclosing-circle-{contour_index}",
                "label": f"circle {contour_index}",
                "circle": {
                    "center_x": float(center_xy[0]),
                    "center_y": float(center_xy[1]),
                    "radius": float(radius),
                },
                "target_parameters": ["selected_contour_index"],
                "parameters": {"selected_contour_index": contour_index},
            }
        )
    return overlays
