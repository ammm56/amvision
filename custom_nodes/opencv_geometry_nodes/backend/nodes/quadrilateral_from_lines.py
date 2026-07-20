"""Quadrilateral From Lines 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.roi import build_roi_payload, polygon_area, polygon_bbox_xyxy
from backend.nodes.debug_image_panel import build_debug_image_preview_output, build_polygon_overlay
from backend.nodes.parameter_utils import is_empty_parameter
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.line_geometry import line_intersection, select_line
from custom_nodes._opencv_shared.backend.runtime.payloads import require_lines_payload


NODE_TYPE_ID = "custom.opencv.quadrilateral-from-lines"
LINE_PORTS = ("top", "right", "bottom", "left")


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从显式连接的 Top/Right/Bottom/Left 直线构建凸四边形 ROI。"""

    selected_lines: dict[str, dict[str, object]] = {}
    source_keys: set[str] = set()
    source_image: dict[str, object] | None = None
    for port_name in LINE_PORTS:
        payload = require_lines_payload(request.input_values.get(port_name))
        selected_lines[port_name] = select_line(
            payload["items"],
            one_based_index=_read_positive_int(
                request.parameters.get(f"{port_name}_line_index"),
                field_name=f"{port_name}_line_index",
            ),
            field_name=f"{port_name}_line_index",
        )
        source_key = payload.get("source_object_key")
        if isinstance(source_key, str) and source_key:
            source_keys.add(source_key)
        if source_image is None and isinstance(payload.get("source_image"), dict):
            source_image = require_image_payload(payload["source_image"])
    if len(source_keys) > 1:
        raise InvalidRequestError("Quadrilateral From Lines 的四个输入必须来自同一张图片")

    points = [
        line_intersection(selected_lines["top"], selected_lines["left"]),
        line_intersection(selected_lines["top"], selected_lines["right"]),
        line_intersection(selected_lines["bottom"], selected_lines["right"]),
        line_intersection(selected_lines["bottom"], selected_lines["left"]),
    ]
    _validate_quadrilateral(points)
    width = max(_distance(points[0], points[1]), _distance(points[3], points[2]))
    height = max(_distance(points[0], points[3]), _distance(points[1], points[2]))
    min_width = _read_positive_float(request.parameters.get("min_width"), "min_width", 1.0)
    min_height = _read_positive_float(request.parameters.get("min_height"), "min_height", 1.0)
    if width < min_width or height < min_height:
        raise InvalidRequestError(
            "Quadrilateral From Lines 的四边形尺寸小于配置下限",
            details={"width": width, "height": height, "min_width": min_width, "min_height": min_height},
        )
    area = polygon_area(points)
    roi = build_roi_payload(
        roi_id=_read_text(request.parameters.get("roi_id"), "line-quadrilateral"),
        display_name=_read_text(request.parameters.get("display_name"), "Line Quadrilateral"),
        roi_kind="polygon",
        bbox_xyxy=polygon_bbox_xyxy(points),
        polygon_xy=points,
        area=area,
        source_image=source_image,
    )
    outputs: dict[str, object] = {
        "roi": roi,
        "summary": build_value_payload(
            {
                "polygon_xy": points,
                "area": round(area, 4),
                "width": round(width, 4),
                "height": round(height, 4),
                "source_object_key": next(iter(source_keys), None),
            }
        ),
    }
    if source_image is not None:
        outputs.update(
            build_debug_image_preview_output(
                request,
                image_payload=source_image,
                title="Quadrilateral From Lines",
                artifact_name="quadrilateral-from-lines-debug-preview",
                overlays=[
                    build_polygon_overlay(
                        overlay_id="line-quadrilateral",
                        label="Quadrilateral",
                        polygon_xy=points,
                        kind="quadrilateral",
                    )
                ],
            )
        )
    return outputs


def _validate_quadrilateral(points: list[list[float]]) -> None:
    """验证显式 Top/Right/Bottom/Left 交点组成凸且顺序正确的四边形。"""

    top_left, top_right, bottom_right, bottom_left = points
    if top_left[0] >= top_right[0] or bottom_left[0] >= bottom_right[0]:
        raise InvalidRequestError("Quadrilateral From Lines 的左右直线顺序无效")
    if top_left[1] >= bottom_left[1] or top_right[1] >= bottom_right[1]:
        raise InvalidRequestError("Quadrilateral From Lines 的上下直线顺序无效")
    cross_products: list[float] = []
    for index in range(4):
        first = points[index]
        second = points[(index + 1) % 4]
        third = points[(index + 2) % 4]
        cross_products.append(
            (second[0] - first[0]) * (third[1] - second[1])
            - (second[1] - first[1]) * (third[0] - second[0])
        )
    if any(abs(value) <= 1e-8 for value in cross_products) or not (
        all(value > 0 for value in cross_products) or all(value < 0 for value in cross_products)
    ):
        raise InvalidRequestError("Quadrilateral From Lines 的交点不能组成凸四边形")


def _read_positive_int(raw_value: object, *, field_name: str) -> int:
    """读取一基 line index。"""

    if is_empty_parameter(raw_value):
        return 1
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 1:
        raise InvalidRequestError(f"{field_name} 必须是正整数")
    return raw_value


def _read_positive_float(raw_value: object, field_name: str, default_value: float) -> float:
    """读取正浮点数。"""

    if is_empty_parameter(raw_value):
        return default_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数字")
    value = float(raw_value)
    if value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return value


def _read_text(raw_value: object, default_value: str) -> str:
    """读取可选文本。"""

    return raw_value.strip() if isinstance(raw_value, str) and raw_value.strip() else default_value


def _distance(first: list[float], second: list[float]) -> float:
    """计算两个点的欧氏距离。"""

    return math.hypot(second[0] - first[0], second[1] - first[1])
