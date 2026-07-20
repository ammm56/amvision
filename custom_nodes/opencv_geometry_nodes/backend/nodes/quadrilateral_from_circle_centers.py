"""Quadrilateral From Circle Centers 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.roi import (
    build_roi_payload,
    polygon_area,
    polygon_bbox_xyxy,
)
from backend.nodes.debug_image_panel import (
    build_circle_overlay,
    build_debug_image_preview_output,
    build_polygon_overlay,
)
from backend.nodes.parameter_utils import is_empty_parameter
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.payloads import require_circles_payload


NODE_TYPE_ID = "custom.opencv.quadrilateral-from-circle-centers"
CORNER_PORTS = ("top_left", "top_right", "bottom_right", "bottom_left")


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从四个显式 circle 输入构建有序四边形 ROI。"""

    points: list[list[float]] = []
    selected_circles: list[dict[str, object]] = []
    source_images: list[dict[str, object]] = []
    source_object_keys: set[str] = set()
    for port_name in CORNER_PORTS:
        circles_payload = require_circles_payload(request.input_values.get(port_name))
        selected_circle = _select_circle(
            circles_payload,
            selected_index=_read_selected_index(
                request.parameters.get(f"{port_name}_index"),
                field_name=f"{port_name}_index",
            ),
            port_name=port_name,
        )
        center_xy = selected_circle["center_xy"]
        points.append([float(center_xy[0]), float(center_xy[1])])
        selected_circles.append(selected_circle)
        source_image = circles_payload.get("source_image")
        if isinstance(source_image, dict):
            source_images.append(require_image_payload(source_image))
        source_object_key = circles_payload.get("source_object_key")
        if isinstance(source_object_key, str) and source_object_key:
            source_object_keys.add(source_object_key)

    if len(source_object_keys) > 1:
        raise InvalidRequestError(
            "quadrilateral-from-circle-centers 的四个输入必须来自同一张图片",
            details={"source_object_keys": sorted(source_object_keys)},
        )
    points = _apply_outsets(
        points,
        left=_read_non_negative_float(request.parameters.get("left_outset"), field_name="left_outset"),
        right=_read_non_negative_float(request.parameters.get("right_outset"), field_name="right_outset"),
        top=_read_non_negative_float(request.parameters.get("top_outset"), field_name="top_outset"),
        bottom=_read_non_negative_float(
            request.parameters.get("bottom_outset"), field_name="bottom_outset"
        ),
    )
    _validate_corner_order(points)
    bbox_xyxy = polygon_bbox_xyxy(points)
    quad_width = max(
        _point_distance(points[0], points[1]),
        _point_distance(points[3], points[2]),
    )
    quad_height = max(
        _point_distance(points[0], points[3]),
        _point_distance(points[1], points[2]),
    )
    min_width = _read_positive_float(
        request.parameters.get("min_width"), field_name="min_width", default_value=1.0
    )
    min_height = _read_positive_float(
        request.parameters.get("min_height"), field_name="min_height", default_value=1.0
    )
    if quad_width < min_width or quad_height < min_height:
        raise InvalidRequestError(
            "quadrilateral-from-circle-centers 的四边形尺寸小于配置下限",
            details={
                "width": round(quad_width, 4),
                "height": round(quad_height, 4),
                "min_width": min_width,
                "min_height": min_height,
            },
        )
    area = polygon_area(points)
    if area <= 0:
        raise InvalidRequestError("quadrilateral-from-circle-centers 生成了零面积四边形")

    source_image = source_images[0] if source_images else None
    roi_payload = build_roi_payload(
        roi_id=_read_text(request.parameters.get("roi_id"), default_value="circle-quadrilateral"),
        display_name=_read_text(
            request.parameters.get("display_name"), default_value="Circle Quadrilateral"
        ),
        roi_kind="polygon",
        bbox_xyxy=bbox_xyxy,
        polygon_xy=points,
        area=area,
        source_image=source_image,
    )
    outputs: dict[str, object] = {
        "roi": roi_payload,
        "summary": build_value_payload(
            {
                "polygon_xy": points,
                "bbox_xyxy": bbox_xyxy,
                "area": round(area, 4),
                "width": round(quad_width, 4),
                "height": round(quad_height, 4),
                "source_object_key": next(iter(source_object_keys), None),
                "selected_circle_indices": {
                    port_name: int(circle["circle_index"])
                    for port_name, circle in zip(CORNER_PORTS, selected_circles, strict=True)
                },
            }
        ),
    }
    if source_image is not None:
        outputs.update(
            build_debug_image_preview_output(
                request,
                image_payload=source_image,
                title="Quadrilateral From Circle Centers",
                artifact_name="quadrilateral-from-circle-centers-debug-preview",
                overlays=_build_overlays(points=points, circles=selected_circles),
            )
        )
    return outputs


def _select_circle(
    payload: dict[str, object],
    *,
    selected_index: int,
    port_name: str,
) -> dict[str, object]:
    """按一基序号选择一个 circle，禁止隐式猜测角点。"""

    items = payload["items"]
    if not items:
        raise InvalidRequestError(
            f"quadrilateral-from-circle-centers 的 {port_name} 没有 circle 结果"
        )
    zero_based_index = selected_index - 1
    if zero_based_index >= len(items):
        raise InvalidRequestError(
            f"quadrilateral-from-circle-centers 的 {port_name}_index 超出 circle 数量",
            details={"selected_index": selected_index, "count": len(items)},
        )
    return dict(items[zero_based_index])


def _read_selected_index(raw_value: object, *, field_name: str) -> int:
    """读取一基 circle 选择序号。"""

    if is_empty_parameter(raw_value):
        return 1
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 1:
        raise InvalidRequestError(f"{field_name} 必须是正整数")
    return int(raw_value)


def _read_positive_float(raw_value: object, *, field_name: str, default_value: float) -> float:
    """读取正浮点参数。"""

    if is_empty_parameter(raw_value):
        return float(default_value)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数字")
    normalized_value = float(raw_value)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return normalized_value


def _read_non_negative_float(raw_value: object, *, field_name: str) -> float:
    """读取非负浮点参数。"""

    if is_empty_parameter(raw_value):
        return 0.0
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数字")
    normalized_value = float(raw_value)
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return normalized_value


def _read_text(raw_value: object, *, default_value: str) -> str:
    """读取可选文本参数。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        return default_value
    return raw_value.strip()


def _validate_corner_order(points: list[list[float]]) -> None:
    """验证 TL/TR/BR/BL 顺序、凸性和非自交。"""

    top_left, top_right, bottom_right, bottom_left = points
    if top_left[0] >= top_right[0] or bottom_left[0] >= bottom_right[0]:
        raise InvalidRequestError("quadrilateral-from-circle-centers 的左右角点顺序无效")
    if top_left[1] >= bottom_left[1] or top_right[1] >= bottom_right[1]:
        raise InvalidRequestError("quadrilateral-from-circle-centers 的上下角点顺序无效")
    cross_products: list[float] = []
    for index in range(4):
        point_a = points[index]
        point_b = points[(index + 1) % 4]
        point_c = points[(index + 2) % 4]
        cross_products.append(
            (point_b[0] - point_a[0]) * (point_c[1] - point_b[1])
            - (point_b[1] - point_a[1]) * (point_c[0] - point_b[0])
        )
    if any(value == 0 for value in cross_products) or not (
        all(value > 0 for value in cross_products)
        or all(value < 0 for value in cross_products)
    ):
        raise InvalidRequestError("quadrilateral-from-circle-centers 的角点不能组成凸四边形")


def _apply_outsets(
    points: list[list[float]],
    *,
    left: float,
    right: float,
    top: float,
    bottom: float,
) -> list[list[float]]:
    """沿四边形局部水平和垂直方向向外扩展角点。"""

    if not any((left, right, top, bottom)):
        return [list(point) for point in points]
    top_left, top_right, bottom_right, bottom_left = points
    left_midpoint = [
        (top_left[0] + bottom_left[0]) / 2.0,
        (top_left[1] + bottom_left[1]) / 2.0,
    ]
    right_midpoint = [
        (top_right[0] + bottom_right[0]) / 2.0,
        (top_right[1] + bottom_right[1]) / 2.0,
    ]
    top_midpoint = [
        (top_left[0] + top_right[0]) / 2.0,
        (top_left[1] + top_right[1]) / 2.0,
    ]
    bottom_midpoint = [
        (bottom_left[0] + bottom_right[0]) / 2.0,
        (bottom_left[1] + bottom_right[1]) / 2.0,
    ]
    horizontal_unit = _unit_vector(left_midpoint, right_midpoint, field_name="horizontal axis")
    vertical_unit = _unit_vector(top_midpoint, bottom_midpoint, field_name="vertical axis")
    return [
        _offset_point(top_left, horizontal_unit, -left, vertical_unit, -top),
        _offset_point(top_right, horizontal_unit, right, vertical_unit, -top),
        _offset_point(bottom_right, horizontal_unit, right, vertical_unit, bottom),
        _offset_point(bottom_left, horizontal_unit, -left, vertical_unit, bottom),
    ]


def _unit_vector(
    point_a: list[float], point_b: list[float], *, field_name: str
) -> tuple[float, float]:
    """计算有向单位向量。"""

    distance = _point_distance(point_a, point_b)
    if distance <= 1e-6:
        raise InvalidRequestError(f"quadrilateral-from-circle-centers 的 {field_name} 长度为 0")
    return ((point_b[0] - point_a[0]) / distance, (point_b[1] - point_a[1]) / distance)


def _offset_point(
    point: list[float],
    horizontal_unit: tuple[float, float],
    horizontal_distance: float,
    vertical_unit: tuple[float, float],
    vertical_distance: float,
) -> list[float]:
    """按局部坐标轴偏移一个点。"""

    return [
        round(
            point[0]
            + horizontal_unit[0] * horizontal_distance
            + vertical_unit[0] * vertical_distance,
            4,
        ),
        round(
            point[1]
            + horizontal_unit[1] * horizontal_distance
            + vertical_unit[1] * vertical_distance,
            4,
        ),
    ]


def _point_distance(point_a: list[float], point_b: list[float]) -> float:
    """计算两点欧氏距离。"""

    delta_x = point_b[0] - point_a[0]
    delta_y = point_b[1] - point_a[1]
    return (delta_x * delta_x + delta_y * delta_y) ** 0.5


def _build_overlays(
    *,
    points: list[list[float]],
    circles: list[dict[str, object]],
) -> list[dict[str, object]]:
    """构建四个 circle 和最终 quadrilateral 的调试 overlay。"""

    overlays: list[dict[str, object]] = [
        build_polygon_overlay(
            overlay_id="circle-quadrilateral",
            label="Quadrilateral",
            polygon_xy=points,
            kind="quadrilateral",
        )
    ]
    for port_name, circle in zip(CORNER_PORTS, circles, strict=True):
        center_xy = circle["center_xy"]
        overlays.append(
            build_circle_overlay(
                overlay_id=f"corner-{port_name}",
                label=port_name,
                center_x=float(center_xy[0]),
                center_y=float(center_xy[1]),
                radius=float(circle["radius"]),
            )
        )
    return overlays
