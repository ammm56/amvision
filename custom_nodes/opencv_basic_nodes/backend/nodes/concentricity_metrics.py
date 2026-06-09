"""Concentricity Metrics 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    measure_point_distance,
    require_circles_payload,
    require_positive_int,
    select_circle_item,
)


NODE_TYPE_ID = "custom.opencv.concentricity-metrics"


def _read_circle_strategy(raw_value: object, *, default_value: str) -> str:
    """读取 circle 选择策略。"""

    if raw_value in {None, ""}:
        return default_value
    if not isinstance(raw_value, str):
        raise InvalidRequestError("circle_strategy 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"first", "largest", "smallest", "circle-index"}:
        raise InvalidRequestError("circle_strategy 不在支持的列表中")
    return normalized_value


def _read_optional_circle_index(raw_value: object, *, field_name: str) -> int | None:
    """读取可选 circle_index。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name=field_name)


def _read_output_metric(raw_value: object) -> str:
    """读取输出指标类型。"""

    if raw_value in {None, ""}:
        return "center_distance_pixels"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("output_metric 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {
        "center_distance_pixels",
        "normalized_center_offset",
        "radius_delta_pixels",
        "diameter_delta_pixels",
    }:
        raise InvalidRequestError(
            "output_metric 仅支持 center_distance_pixels、normalized_center_offset、radius_delta_pixels 或 diameter_delta_pixels"
        )
    return normalized_value


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算两圆之间的同心度和尺寸差。"""

    circles_payload = require_circles_payload(request.input_values.get("circles"))
    circle_a_strategy = _read_circle_strategy(request.parameters.get("circle_a_strategy"), default_value="largest")
    circle_b_strategy = _read_circle_strategy(request.parameters.get("circle_b_strategy"), default_value="smallest")
    circle_a_index = _read_optional_circle_index(request.parameters.get("circle_a_index"), field_name="circle_a_index")
    circle_b_index = _read_optional_circle_index(request.parameters.get("circle_b_index"), field_name="circle_b_index")
    output_metric = _read_output_metric(request.parameters.get("output_metric"))
    selected_circle_a = select_circle_item(
        circles_payload["items"],
        strategy=circle_a_strategy,
        circle_index=circle_a_index,
    )
    selected_circle_b = select_circle_item(
        circles_payload["items"],
        strategy=circle_b_strategy,
        circle_index=circle_b_index,
    )
    if int(selected_circle_a["circle_index"]) == int(selected_circle_b["circle_index"]):
        raise InvalidRequestError("concentricity-metrics 需要两个不同的 circle")

    center_distance = measure_point_distance(
        point_a_xy=(float(selected_circle_a["center_xy"][0]), float(selected_circle_a["center_xy"][1])),
        point_b_xy=(float(selected_circle_b["center_xy"][0]), float(selected_circle_b["center_xy"][1])),
    )
    center_distance_pixels = float(center_distance["distance_pixels"])
    radius_a = float(selected_circle_a["radius"])
    radius_b = float(selected_circle_b["radius"])
    max_radius = max(radius_a, radius_b)
    radius_delta_pixels = float(abs(radius_a - radius_b))
    diameter_delta_pixels = float(abs(float(selected_circle_a["diameter"]) - float(selected_circle_b["diameter"])))
    normalized_center_offset = float(center_distance_pixels / max_radius) if max_radius > 0 else 0.0
    measured_value = {
        "center_distance_pixels": center_distance_pixels,
        "normalized_center_offset": normalized_center_offset,
        "radius_delta_pixels": radius_delta_pixels,
        "diameter_delta_pixels": diameter_delta_pixels,
    }[output_metric]
    return {
        "value": build_value_payload(round(measured_value, 4)),
        "summary": build_value_payload(
            {
                "circle_count": len(circles_payload["items"]),
                "selected_circle_a_index": int(selected_circle_a["circle_index"]),
                "selected_circle_b_index": int(selected_circle_b["circle_index"]),
                "circle_a_strategy": circle_a_strategy,
                "circle_b_strategy": circle_b_strategy,
                "output_metric": output_metric,
                "center_distance_pixels": round(center_distance_pixels, 4),
                "normalized_center_offset": round(normalized_center_offset, 6),
                "radius_delta_pixels": round(radius_delta_pixels, 4),
                "diameter_delta_pixels": round(diameter_delta_pixels, 4),
                "radius_ratio": round(float(min(radius_a, radius_b) / max_radius), 6) if max_radius > 0 else None,
                "circle_a_center_xy": list(selected_circle_a["center_xy"]),
                "circle_b_center_xy": list(selected_circle_b["center_xy"]),
                "circle_a_radius": round(radius_a, 4),
                "circle_b_radius": round(radius_b, 4),
            }
        ),
    }
