"""Fit Ellipse 节点实现。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import (
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_interaction_tool,
    build_numeric_control,
    build_polygon_overlay,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.geometry import compute_contour_metrics_from_points
from custom_nodes._opencv_shared.backend.runtime.payloads import require_contours_payload
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.validators import require_positive_int


NODE_TYPE_ID = "custom.opencv.fit-ellipse"


def _build_ellipses_payload(
    *,
    items: list[dict[str, object]],
    source_image: object | None,
    source_object_key: str | None,
) -> dict[str, object]:
    """构建 ellipses.v1 payload。"""

    payload: dict[str, object] = {
        "items": [dict(item) for item in items],
        "count": len(items),
    }
    if isinstance(source_image, dict):
        payload["source_image"] = dict(source_image)
    if isinstance(source_object_key, str) and source_object_key:
        payload["source_object_key"] = source_object_key
    return payload


def _read_optional_limit(raw_value: object) -> int | None:
    """读取可选 limit。"""

    if is_empty_parameter(raw_value):
        return None
    return require_positive_int(raw_value, field_name="limit")


def _read_optional_selected_contour_index(raw_value: object) -> int | None:
    """读取可选点选 contour 序号。"""

    if is_empty_parameter(raw_value):
        return None
    return require_positive_int(raw_value, field_name="selected_contour_index")


def _read_sort_by(raw_value: object) -> str:
    """读取排序字段。"""

    if is_empty_parameter(raw_value):
        return "major_axis"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("fit-ellipse 节点的 sort_by 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {
        "ellipse_index",
        "contour_index",
        "major_axis",
        "minor_axis",
        "area",
        "fill_ratio",
        "angle_deg",
        "center_x",
        "center_y",
    }:
        raise InvalidRequestError("fit-ellipse 节点的 sort_by 不在支持列表中")
    return normalized_value


def _read_descending(raw_value: object) -> bool:
    """读取 descending。"""

    if is_empty_parameter(raw_value):
        return True
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("fit-ellipse 节点的 descending 必须是布尔值")
    return raw_value


def _normalize_angle_deg(*, width_value: float, height_value: float, angle_value: float) -> float:
    """把 OpenCV ellipse 角度规整到主轴方向。"""

    normalized_angle = float(angle_value if width_value >= height_value else angle_value + 90.0)
    normalized_angle = float(normalized_angle % 180.0)
    if normalized_angle >= 90.0:
        normalized_angle -= 180.0
    return round(normalized_angle, 4)


def _estimate_ellipse_perimeter(*, major_axis: float, minor_axis: float) -> float:
    """按 Ramanujan 近似计算椭圆周长。"""

    semi_major = float(major_axis / 2.0)
    semi_minor = float(minor_axis / 2.0)
    return float(
        math.pi
        * (
            3.0 * (semi_major + semi_minor)
            - math.sqrt((3.0 * semi_major + semi_minor) * (semi_major + 3.0 * semi_minor))
        )
    )


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对 contour 集合执行椭圆拟合。"""

    cv2_module, np_module = require_opencv_imports()
    contours_payload = require_contours_payload(request.input_values.get("contours"))
    sort_by = _read_sort_by(request.parameters.get("sort_by"))
    descending = _read_descending(request.parameters.get("descending"))
    limit = _read_optional_limit(request.parameters.get("limit"))
    selected_contour_index = _read_optional_selected_contour_index(request.parameters.get("selected_contour_index"))

    ellipse_items: list[dict[str, object]] = []
    skipped_contour_indices: list[int] = []
    for contour_item in contours_payload["items"]:
        contour_index = int(contour_item["contour_index"])
        if selected_contour_index is not None and contour_index != selected_contour_index:
            continue
        point_count = int(contour_item["point_count"])
        if point_count < 5:
            skipped_contour_indices.append(contour_index)
            continue
        point_array = np_module.array(contour_item["points"], dtype=np_module.float32)
        contour_metrics = compute_contour_metrics_from_points(
            points=contour_item["points"],
            cv2_module=cv2_module,
            np_module=np_module,
        )
        center_xy, size_wh, angle_value = cv2_module.fitEllipse(point_array)
        axis_width = round(float(size_wh[0]), 4)
        axis_height = round(float(size_wh[1]), 4)
        major_axis = round(max(axis_width, axis_height), 4)
        minor_axis = round(min(axis_width, axis_height), 4)
        area = round(float(math.pi * (major_axis / 2.0) * (minor_axis / 2.0)), 4)
        contour_area = round(float(contour_metrics["area"]), 4)
        fill_ratio = round(float(contour_area / area), 4) if area > 0 else 0.0
        center_x = round(float(center_xy[0]), 4)
        center_y = round(float(center_xy[1]), 4)
        box_points = cv2_module.boxPoints((center_xy, size_wh, angle_value)).tolist()
        bbox_x_values = [float(point[0]) for point in box_points]
        bbox_y_values = [float(point[1]) for point in box_points]
        ellipse_items.append(
            {
                "ellipse_index": len(ellipse_items) + 1,
                "contour_index": contour_index,
                "point_count": point_count,
                "center_xy": [center_x, center_y],
                "center_x": center_x,
                "center_y": center_y,
                "size_wh": [axis_width, axis_height],
                "width": axis_width,
                "height": axis_height,
                "major_axis": major_axis,
                "minor_axis": minor_axis,
                "angle_deg": _normalize_angle_deg(
                    width_value=axis_width,
                    height_value=axis_height,
                    angle_value=float(angle_value),
                ),
                "bbox_xyxy": [
                    round(min(bbox_x_values), 4),
                    round(min(bbox_y_values), 4),
                    round(max(bbox_x_values), 4),
                    round(max(bbox_y_values), 4),
                ],
                "box_points": [
                    [round(float(point[0]), 4), round(float(point[1]), 4)]
                    for point in box_points
                ],
                "area": area,
                "perimeter": round(
                    _estimate_ellipse_perimeter(major_axis=major_axis, minor_axis=minor_axis),
                    4,
                ),
                "contour_area": contour_area,
                "fill_ratio": fill_ratio,
            }
        )

    ellipse_items.sort(key=lambda current_item: current_item[sort_by], reverse=descending)
    if limit is not None:
        ellipse_items = ellipse_items[:limit]
    for ellipse_index, ellipse_item in enumerate(ellipse_items, start=1):
        ellipse_item["ellipse_index"] = ellipse_index

    source_image = contours_payload.get("source_image")
    source_object_key = (
        contours_payload.get("source_object_key")
        if isinstance(contours_payload.get("source_object_key"), str)
        else None
    )
    outputs: dict[str, object] = {
        "ellipses": _build_ellipses_payload(
            items=ellipse_items,
            source_image=source_image,
            source_object_key=source_object_key,
        ),
        "summary": build_value_payload(
            {
                "count": len(ellipse_items),
                "sort_by": sort_by,
                "descending": descending,
                "limit": limit,
                "selected_contour_index": selected_contour_index,
                "skipped_count": len(skipped_contour_indices),
                "skipped_contour_indices": skipped_contour_indices,
                "max_major_axis": round(max((float(item["major_axis"]) for item in ellipse_items), default=0.0), 4),
                "mean_fill_ratio": round(
                    (
                        sum(float(item["fill_ratio"]) for item in ellipse_items) / len(ellipse_items)
                        if ellipse_items
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
                title="Fit Ellipse",
                artifact_name="fit-ellipse-debug-preview",
                overlays=_build_ellipse_overlays(ellipse_items),
                interaction=_build_fit_ellipse_interaction(limit=limit),
            )
        )
    return outputs


def _build_fit_ellipse_interaction(*, limit: int | None) -> dict[str, object]:
    """声明 Fit Ellipse 在图片面板中的椭圆结果点选能力。"""

    return build_debug_panel_interaction(
        tools=[
            build_interaction_tool(
                "contour",
                "椭圆点选",
                ["selected_contour_index"],
                extra={"min_points": 5},
            ),
        ],
        controls=[
            build_numeric_control("limit", "Limit", limit or 20, min_value=1.0, max_value=200.0, step=1.0),
        ],
    )


def _build_ellipse_overlays(ellipse_items: list[dict[str, object]]) -> list[dict[str, object]]:
    """把拟合椭圆结果转换为图片面板 polygon overlay。"""

    overlays: list[dict[str, object]] = []
    for ellipse_item in ellipse_items[:120]:
        center_xy = ellipse_item.get("center_xy")
        size_wh = ellipse_item.get("size_wh")
        angle_deg = ellipse_item.get("angle_deg")
        if (
            not isinstance(center_xy, list)
            or len(center_xy) < 2
            or not isinstance(size_wh, list)
            or len(size_wh) < 2
            or not isinstance(angle_deg, (int, float))
        ):
            continue
        ellipse_index = int(ellipse_item.get("ellipse_index", len(overlays) + 1))
        contour_index = int(ellipse_item.get("contour_index", ellipse_index))
        overlays.append(
            build_polygon_overlay(
                kind="ellipse",
                overlay_id=f"fit-ellipse-{contour_index}",
                label=f"ellipse {contour_index}",
                polygon_xy=_approximate_ellipse_points(
                    center_x=float(center_xy[0]),
                    center_y=float(center_xy[1]),
                    width=float(size_wh[0]),
                    height=float(size_wh[1]),
                    angle_deg=float(angle_deg),
                    point_count=72,
                ),
                target_parameters=["selected_contour_index"],
                parameters={"selected_contour_index": contour_index},
            )
        )
    return overlays


def _approximate_ellipse_points(
    *,
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    angle_deg: float,
    point_count: int,
) -> list[list[float]]:
    """用 polygon 点近似椭圆，复用前端已有 overlay 协议。"""

    radius_x = max(0.0, float(width) / 2.0)
    radius_y = max(0.0, float(height) / 2.0)
    angle_rad = math.radians(angle_deg)
    cos_value = math.cos(angle_rad)
    sin_value = math.sin(angle_rad)
    points: list[list[float]] = []
    for index in range(max(12, int(point_count))):
        theta = 2.0 * math.pi * float(index) / float(max(12, int(point_count)))
        local_x = radius_x * math.cos(theta)
        local_y = radius_y * math.sin(theta)
        points.append(
            [
                round(center_x + local_x * cos_value - local_y * sin_value, 4),
                round(center_y + local_x * sin_value + local_y * cos_value, 4),
            ]
        )
    return points
