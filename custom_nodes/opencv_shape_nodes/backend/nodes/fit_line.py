"""Fit Line 节点实现。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import (
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_interaction_tool,
    build_line_overlay,
    build_numeric_control,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.payloads import (
    build_lines_payload,
    require_contours_payload,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_boolean,
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.performance import read_find_result_limit


NODE_TYPE_ID = "custom.opencv.fit-line"


def _read_optional_limit(raw_value: object) -> int | None:
    """读取可选 limit。"""

    if is_empty_parameter(raw_value):
        return None
    return require_positive_int(raw_value, field_name="limit")


def _read_positive_float(raw_value: object, *, field_name: str, default_value: float) -> float:
    """读取正浮点参数。"""

    if is_empty_parameter(raw_value):
        return float(default_value)
    normalized_value = require_non_negative_float(raw_value, field_name=field_name)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return float(normalized_value)


def _normalize_sort_by(value: object) -> str:
    """规范化 fit-line 的排序字段。"""

    if not isinstance(value, str) or not value.strip():
        return "length_pixels"
    normalized_value = value.strip().lower()
    if normalized_value not in {
        "line_index",
        "contour_index",
        "length_pixels",
        "angle_deg",
        "midpoint_x",
        "midpoint_y",
    }:
        raise InvalidRequestError("sort_by 不在支持的 fit-line 排序字段列表中")
    return normalized_value


def _normalize_distance_type(value: object, *, cv2_module: object) -> int:
    """把 fitLine distance type 解析为 OpenCV 常量。"""

    if not isinstance(value, str) or not value.strip():
        return getattr(cv2_module, "DIST_L2")
    normalized_value = value.strip().lower()
    distance_mapping = {
        "l2": getattr(cv2_module, "DIST_L2"),
        "l1": getattr(cv2_module, "DIST_L1"),
        "l12": getattr(cv2_module, "DIST_L12"),
        "fair": getattr(cv2_module, "DIST_FAIR"),
        "welsch": getattr(cv2_module, "DIST_WELSCH"),
        "huber": getattr(cv2_module, "DIST_HUBER"),
    }
    resolved_value = distance_mapping.get(normalized_value)
    if resolved_value is None:
        raise InvalidRequestError("distance_type 不在支持的 fit-line 距离类型列表中")
    return int(resolved_value)


def _normalize_angle_deg(*, dx_pixels: float, dy_pixels: float) -> float:
    """把线段方向角规整到更稳定的无方向语义。"""

    angle_deg = float(math.degrees(math.atan2(dy_pixels, dx_pixels)))
    angle_deg = float(angle_deg % 180.0)
    if angle_deg >= 90.0:
        angle_deg -= 180.0
    return round(angle_deg, 4)


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对 contour 集合执行最小二乘拟合直线。"""

    cv2_module, np_module = require_opencv_imports()
    contours_payload = require_contours_payload(request.input_values.get("contours"))
    distance_type = _normalize_distance_type(request.parameters.get("distance_type"), cv2_module=cv2_module)
    reps = _read_positive_float(request.parameters.get("reps"), field_name="reps", default_value=0.01)
    aeps = _read_positive_float(request.parameters.get("aeps"), field_name="aeps", default_value=0.01)
    sort_by = _normalize_sort_by(request.parameters.get("sort_by"))
    descending = require_boolean(
        request.parameters.get("descending", True),
        field_name="descending",
    )
    limit = read_find_result_limit(request.parameters.get("limit"))

    line_items: list[dict[str, object]] = []
    for line_index, contour_item in enumerate(contours_payload["items"], start=1):
        point_array = np_module.array(contour_item["points"], dtype=np_module.float32)
        if point_array.shape[0] < 2:
            continue
        fit_result = cv2_module.fitLine(point_array, distType=distance_type, param=0, reps=reps, aeps=aeps)
        vx_value = float(fit_result[0][0])
        vy_value = float(fit_result[1][0])
        origin_x = float(fit_result[2][0])
        origin_y = float(fit_result[3][0])
        point_vectors = point_array - np_module.array([origin_x, origin_y], dtype=np_module.float32)
        direction_vector = np_module.array([vx_value, vy_value], dtype=np_module.float32)
        projection_values = point_vectors @ direction_vector
        min_projection = float(np_module.min(projection_values))
        max_projection = float(np_module.max(projection_values))
        start_x = origin_x + vx_value * min_projection
        start_y = origin_y + vy_value * min_projection
        end_x = origin_x + vx_value * max_projection
        end_y = origin_y + vy_value * max_projection
        dx_pixels = float(end_x - start_x)
        dy_pixels = float(end_y - start_y)
        midpoint_x = round((start_x + end_x) / 2.0, 4)
        midpoint_y = round((start_y + end_y) / 2.0, 4)
        line_items.append(
            {
                "line_index": int(line_index),
                "contour_index": int(contour_item["contour_index"]),
                "point_count": int(contour_item["point_count"]),
                "start_xy": [round(start_x, 4), round(start_y, 4)],
                "end_xy": [round(end_x, 4), round(end_y, 4)],
                "origin_xy": [round(origin_x, 4), round(origin_y, 4)],
                "direction_xy": [round(vx_value, 6), round(vy_value, 6)],
                "dx_pixels": round(dx_pixels, 4),
                "dy_pixels": round(dy_pixels, 4),
                "length_pixels": round(float(math.hypot(dx_pixels, dy_pixels)), 4),
                "angle_deg": _normalize_angle_deg(dx_pixels=dx_pixels, dy_pixels=dy_pixels),
                "midpoint_xy": [midpoint_x, midpoint_y],
                "midpoint_x": midpoint_x,
                "midpoint_y": midpoint_y,
                "bbox_xyxy": [
                    round(min(start_x, end_x), 4),
                    round(min(start_y, end_y), 4),
                    round(max(start_x, end_x), 4),
                    round(max(start_y, end_y), 4),
                ],
            }
        )

    line_items.sort(key=lambda current_item: current_item[sort_by], reverse=descending)
    if limit is not None:
        line_items = line_items[:limit]

    source_image = contours_payload.get("source_image")
    source_object_key = (
        contours_payload.get("source_object_key")
        if isinstance(contours_payload.get("source_object_key"), str)
        else None
    )
    outputs: dict[str, object] = {
        "lines": build_lines_payload(
            items=line_items,
            source_image=source_image,
            source_object_key=source_object_key,
        ),
        "summary": build_value_payload(
            {
                "count": len(line_items),
                "sort_by": sort_by,
                "descending": descending,
                "limit": limit,
                "distance_type": str(request.parameters.get("distance_type") or "l2").strip().lower()
                if isinstance(request.parameters.get("distance_type"), str)
                else "l2",
                "reps": reps,
                "aeps": aeps,
                "max_length_pixels": round(
                    max((float(item["length_pixels"]) for item in line_items), default=0.0),
                    4,
                ),
                "mean_length_pixels": round(
                    (
                        sum(float(item["length_pixels"]) for item in line_items) / len(line_items)
                        if line_items
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
                title="Fit Line",
                artifact_name="fit-line-debug-preview",
                overlays=_build_line_overlays(line_items),
                interaction=_build_line_interaction(
                    reps=reps,
                    aeps=aeps,
                    limit=limit,
                ),
            )
        )
    return outputs


def _build_line_interaction(
    *,
    reps: float,
    aeps: float,
    limit: int | None,
) -> dict[str, object]:
    """声明 Fit Line 在图片面板中的线段取参和调参能力。"""

    return build_debug_panel_interaction(
        tools=[
            build_interaction_tool("line", "参考线段", []),
        ],
        controls=[
            build_numeric_control("reps", "REPS", reps, min_value=0.001, max_value=2.0, step=0.001),
            build_numeric_control("aeps", "AEPS", aeps, min_value=0.001, max_value=2.0, step=0.001),
            build_numeric_control("limit", "Limit", limit or 20, min_value=1.0, max_value=200.0, step=1.0),
        ],
    )


def _build_line_overlays(line_items: list[dict[str, object]]) -> list[dict[str, object]]:
    """把拟合直线结果转换为图片面板 overlay。"""

    overlays: list[dict[str, object]] = []
    for line_item in line_items:
        start_xy = line_item.get("start_xy")
        end_xy = line_item.get("end_xy")
        if not isinstance(start_xy, list) or len(start_xy) < 2 or not isinstance(end_xy, list) or len(end_xy) < 2:
            continue
        line_index = int(line_item.get("line_index", len(overlays) + 1))
        overlays.append(
            build_line_overlay(
                overlay_id=f"fit-line-{line_index}",
                label=f"fit line {line_index}",
                line_xyxy=[
                    float(start_xy[0]),
                    float(start_xy[1]),
                    float(end_xy[0]),
                    float(end_xy[1]),
                ],
            )
        )
    return overlays
