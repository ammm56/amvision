"""Parallelism Metrics 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    compute_line_angle_delta_deg,
    measure_point_distance,
    measure_point_to_line,
    normalize_point_xy,
    require_lines_payload,
    require_positive_int,
    select_line_item,
)


NODE_TYPE_ID = "custom.opencv.parallelism-metrics"


def _read_line_strategy(raw_value: object, *, default_value: str) -> str:
    """读取 line 选择策略。"""

    if raw_value in {None, ""}:
        return default_value
    if not isinstance(raw_value, str):
        raise InvalidRequestError("line_strategy 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"first", "longest", "shortest", "line-index"}:
        raise InvalidRequestError("line_strategy 不在支持的列表中")
    return normalized_value


def _read_optional_line_index(raw_value: object, *, field_name: str) -> int | None:
    """读取可选 line_index。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name=field_name)


def _read_output_metric(raw_value: object) -> str:
    """读取输出指标类型。"""

    if raw_value in {None, ""}:
        return "abs_delta_angle_deg"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("output_metric 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {
        "delta_angle_deg",
        "abs_delta_angle_deg",
        "midpoint_offset_pixels",
        "mean_endpoint_offset_pixels",
    }:
        raise InvalidRequestError(
            "output_metric 仅支持 delta_angle_deg、abs_delta_angle_deg、midpoint_offset_pixels 或 mean_endpoint_offset_pixels"
        )
    return normalized_value


def _resolve_line_midpoint_xy(line_item: dict[str, object]) -> tuple[float, float]:
    """读取 line 中点。"""

    midpoint_xy = line_item.get("midpoint_xy")
    if isinstance(midpoint_xy, (list, tuple)) and len(midpoint_xy) >= 2:
        return normalize_point_xy(midpoint_xy, field_name="midpoint_xy")
    start_x, start_y = normalize_point_xy(line_item.get("start_xy"), field_name="start_xy")
    end_x, end_y = normalize_point_xy(line_item.get("end_xy"), field_name="end_xy")
    return float((start_x + end_x) / 2.0), float((start_y + end_y) / 2.0)


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算两条直线的平行度与相对偏移指标。"""

    lines_payload = require_lines_payload(request.input_values.get("lines"))
    line_a_strategy = _read_line_strategy(request.parameters.get("line_a_strategy"), default_value="longest")
    line_b_strategy = _read_line_strategy(request.parameters.get("line_b_strategy"), default_value="shortest")
    line_a_index = _read_optional_line_index(request.parameters.get("line_a_index"), field_name="line_a_index")
    line_b_index = _read_optional_line_index(request.parameters.get("line_b_index"), field_name="line_b_index")
    output_metric = _read_output_metric(request.parameters.get("output_metric"))
    selected_line_a = select_line_item(lines_payload["items"], strategy=line_a_strategy, line_index=line_a_index)
    selected_line_b = select_line_item(lines_payload["items"], strategy=line_b_strategy, line_index=line_b_index)
    if int(selected_line_a["line_index"]) == int(selected_line_b["line_index"]):
        raise InvalidRequestError("parallelism-metrics 需要两条不同的 line")

    delta_angle_deg = float(
        compute_line_angle_delta_deg(
            angle_a_deg=selected_line_a["angle_deg"],
            angle_b_deg=selected_line_b["angle_deg"],
        )
    )
    abs_delta_angle_deg = float(abs(delta_angle_deg))
    line_b_start_xy = normalize_point_xy(selected_line_b["start_xy"], field_name="line_b.start_xy")
    line_b_end_xy = normalize_point_xy(selected_line_b["end_xy"], field_name="line_b.end_xy")
    line_b_midpoint_xy = _resolve_line_midpoint_xy(selected_line_b)
    start_offset = measure_point_to_line(point_xy=line_b_start_xy, line_item=selected_line_a)
    end_offset = measure_point_to_line(point_xy=line_b_end_xy, line_item=selected_line_a)
    midpoint_offset = measure_point_to_line(point_xy=line_b_midpoint_xy, line_item=selected_line_a)
    midpoint_distance = measure_point_distance(
        point_a_xy=_resolve_line_midpoint_xy(selected_line_a),
        point_b_xy=line_b_midpoint_xy,
    )
    mean_endpoint_offset_pixels = float(
        (float(start_offset["distance_pixels"]) + float(end_offset["distance_pixels"])) / 2.0
    )
    measured_value = {
        "delta_angle_deg": delta_angle_deg,
        "abs_delta_angle_deg": abs_delta_angle_deg,
        "midpoint_offset_pixels": float(midpoint_offset["distance_pixels"]),
        "mean_endpoint_offset_pixels": mean_endpoint_offset_pixels,
    }[output_metric]
    return {
        "value": build_value_payload(round(measured_value, 4)),
        "summary": build_value_payload(
            {
                "line_count": len(lines_payload["items"]),
                "selected_line_a_index": int(selected_line_a["line_index"]),
                "selected_line_b_index": int(selected_line_b["line_index"]),
                "line_a_strategy": line_a_strategy,
                "line_b_strategy": line_b_strategy,
                "output_metric": output_metric,
                "line_a_angle_deg": round(float(selected_line_a["angle_deg"]), 4),
                "line_b_angle_deg": round(float(selected_line_b["angle_deg"]), 4),
                "delta_angle_deg": round(delta_angle_deg, 4),
                "abs_delta_angle_deg": round(abs_delta_angle_deg, 4),
                "start_offset_pixels": round(float(start_offset["distance_pixels"]), 4),
                "end_offset_pixels": round(float(end_offset["distance_pixels"]), 4),
                "midpoint_offset_pixels": round(float(midpoint_offset["distance_pixels"]), 4),
                "mean_endpoint_offset_pixels": round(mean_endpoint_offset_pixels, 4),
                "line_a_length_pixels": round(float(selected_line_a["length_pixels"]), 4),
                "line_b_length_pixels": round(float(selected_line_b["length_pixels"]), 4),
                "midpoint_center_distance_pixels": round(float(midpoint_distance["distance_pixels"]), 4),
                "line_a_midpoint_xy": [
                    round(float(_resolve_line_midpoint_xy(selected_line_a)[0]), 4),
                    round(float(_resolve_line_midpoint_xy(selected_line_a)[1]), 4),
                ],
                "line_b_start_xy": [round(float(line_b_start_xy[0]), 4), round(float(line_b_start_xy[1]), 4)],
                "line_b_end_xy": [round(float(line_b_end_xy[0]), 4), round(float(line_b_end_xy[1]), 4)],
                "line_b_midpoint_xy": [round(float(line_b_midpoint_xy[0]), 4), round(float(line_b_midpoint_xy[1]), 4)],
                "start_projection_xy": [
                    round(float(start_offset["projection_x"]), 4),
                    round(float(start_offset["projection_y"]), 4),
                ],
                "end_projection_xy": [
                    round(float(end_offset["projection_x"]), 4),
                    round(float(end_offset["projection_y"]), 4),
                ],
                "midpoint_projection_xy": [
                    round(float(midpoint_offset["projection_x"]), 4),
                    round(float(midpoint_offset["projection_y"]), 4),
                ],
            }
        ),
    }
