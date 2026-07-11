"""Hough Circles 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import build_debug_image_preview_output
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.payloads import build_circles_payload
from custom_nodes._opencv_shared.backend.runtime.images import load_image_matrix
from custom_nodes._opencv_shared.backend.runtime.search_roi import (
    ResolvedSearchRoi,
    build_search_roi_overlay,
    build_search_roi_summary,
    resolve_search_roi,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_float,
    require_non_negative_int,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


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
    search_roi = resolve_search_roi(request, image_matrix=image_matrix)
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
        search_roi.image_matrix,
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
            center_x += float(search_roi.offset_x)
            center_y += float(search_roi.offset_y)
            center_x = round(center_x, 4)
            center_y = round(center_y, 4)
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

    outputs: dict[str, object] = {
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
                **build_search_roi_summary(search_roi),
            }
        ),
    }
    outputs.update(
        build_debug_image_preview_output(
            request,
            image_payload=image_payload,
            title="Hough Circles",
            artifact_name="hough-circles-debug-preview",
            overlays=_build_circle_overlays(circle_items, search_roi=search_roi),
            interaction=_build_circle_interaction(
                dp=dp,
                min_dist=min_dist,
                param1=param1,
                param2=param2,
                min_radius=min_radius,
                max_radius=max_radius,
            ),
        )
    )
    return outputs


def _build_circle_interaction(
    *,
    dp: float,
    min_dist: float,
    param1: float,
    param2: float,
    min_radius: int,
    max_radius: int,
) -> dict[str, object]:
    """声明 Hough Circles 在图片面板中的取参和调参能力。"""

    return {
        "mode": "edit",
        "coordinate_space": "source-image",
        "tools": [
            {
                "tool": "bbox",
                "label": "搜索 ROI",
                "target_parameters": ["search_bbox_xyxy"],
            },
            {
                "tool": "circle",
                "label": "找圆",
                "target_parameters": ["min_dist", "min_radius", "max_radius"],
            },
        ],
        "controls": [
            _build_numeric_control("dp", "DP", dp, min_value=0.1, max_value=4.0, step=0.1),
            _build_numeric_control("min_dist", "Min Dist", min_dist, min_value=1.0, max_value=600.0, step=1.0),
            _build_numeric_control("param1", "Param1", param1, min_value=1.0, max_value=300.0, step=1.0),
            _build_numeric_control("param2", "Param2", param2, min_value=1.0, max_value=200.0, step=1.0),
            _build_numeric_control("min_radius", "Min Radius", min_radius, min_value=0.0, max_value=400.0, step=1.0),
            _build_numeric_control("max_radius", "Max Radius", max_radius, min_value=0.0, max_value=800.0, step=1.0),
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

def _build_circle_overlays(
    circle_items: list[dict[str, object]],
    *,
    search_roi: ResolvedSearchRoi,
) -> list[dict[str, object]]:
    """把 Hough 圆检测结果转换为图片面板 overlay。"""

    overlays: list[dict[str, object]] = []
    search_roi_overlay = build_search_roi_overlay(search_roi)
    if search_roi_overlay is not None:
        overlays.append(search_roi_overlay)
    for circle_item in circle_items:
        center_xy = circle_item.get("center_xy")
        radius = circle_item.get("radius")
        if not isinstance(center_xy, list) or len(center_xy) < 2 or not isinstance(radius, (int, float)):
            continue
        circle_index = circle_item.get("circle_index", len(overlays) + 1)
        overlays.append(
            {
                "kind": "circle",
                "id": f"circle-{circle_index}",
                "label": f"circle {circle_index}",
                "circle": {
                    "center_x": float(center_xy[0]),
                    "center_y": float(center_xy[1]),
                    "radius": float(radius),
                },
            }
        )
    return overlays
