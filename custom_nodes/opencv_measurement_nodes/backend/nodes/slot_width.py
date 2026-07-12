"""Slot Width 节点实现。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.geometry import (
    compute_line_angle_delta_deg,
    measure_point_to_line,
    normalize_point_xy,
    select_line_item,
)
from custom_nodes._opencv_shared.backend.runtime.payloads import require_lines_payload
from custom_nodes._opencv_shared.backend.runtime.validators import require_positive_int


NODE_TYPE_ID = "custom.opencv.slot-width"


def _read_line_strategy(raw_value: object, *, default_value: str) -> str:
    """读取 line 选择策略。"""

    if is_empty_parameter(raw_value):
        return default_value
    if not isinstance(raw_value, str):
        raise InvalidRequestError("line_strategy 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"first", "longest", "shortest", "line-index"}:
        raise InvalidRequestError("line_strategy 不在支持的列表中")
    return normalized_value


def _read_optional_line_index(raw_value: object, *, field_name: str) -> int | None:
    """读取可选 line_index。"""

    if is_empty_parameter(raw_value):
        return None
    return require_positive_int(raw_value, field_name=field_name)


def _read_output_metric(raw_value: object) -> str:
    """读取输出指标类型。"""

    if is_empty_parameter(raw_value):
        return "mean_width_pixels"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("output_metric 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {
        "mean_width_pixels",
        "min_width_pixels",
        "max_width_pixels",
        "midpoint_width_pixels",
    }:
        raise InvalidRequestError(
            "output_metric 仅支持 mean_width_pixels、min_width_pixels、max_width_pixels 或 midpoint_width_pixels"
        )
    return normalized_value


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算两条边线之间的槽宽。"""

    lines_payload = require_lines_payload(request.input_values.get("lines"))
    line_a_strategy = _read_line_strategy(request.parameters.get("line_a_strategy"), default_value="longest")
    line_b_strategy = _read_line_strategy(request.parameters.get("line_b_strategy"), default_value="shortest")
    line_a_index = _read_optional_line_index(request.parameters.get("line_a_index"), field_name="line_a_index")
    line_b_index = _read_optional_line_index(request.parameters.get("line_b_index"), field_name="line_b_index")
    output_metric = _read_output_metric(request.parameters.get("output_metric"))
    selected_line_a = select_line_item(lines_payload["items"], strategy=line_a_strategy, line_index=line_a_index)
    selected_line_b = select_line_item(lines_payload["items"], strategy=line_b_strategy, line_index=line_b_index)
    if int(selected_line_a["line_index"]) == int(selected_line_b["line_index"]):
        raise InvalidRequestError("slot-width 需要两条不同的 line")

    line_b_start_xy = normalize_point_xy(selected_line_b["start_xy"], field_name="line_b.start_xy")
    line_b_end_xy = normalize_point_xy(selected_line_b["end_xy"], field_name="line_b.end_xy")
    line_b_midpoint_xy = normalize_point_xy(selected_line_b["midpoint_xy"], field_name="line_b.midpoint_xy")
    start_width = measure_point_to_line(point_xy=line_b_start_xy, line_item=selected_line_a)
    end_width = measure_point_to_line(point_xy=line_b_end_xy, line_item=selected_line_a)
    midpoint_width = measure_point_to_line(point_xy=line_b_midpoint_xy, line_item=selected_line_a)
    width_values = [
        float(start_width["distance_pixels"]),
        float(end_width["distance_pixels"]),
        float(midpoint_width["distance_pixels"]),
    ]
    mean_width_pixels = float(sum(width_values) / len(width_values))
    min_width_pixels = float(min(width_values))
    max_width_pixels = float(max(width_values))
    midpoint_width_pixels = float(midpoint_width["distance_pixels"])
    measured_value = {
        "mean_width_pixels": mean_width_pixels,
        "min_width_pixels": min_width_pixels,
        "max_width_pixels": max_width_pixels,
        "midpoint_width_pixels": midpoint_width_pixels,
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
                "mean_width_pixels": round(mean_width_pixels, 4),
                "min_width_pixels": round(min_width_pixels, 4),
                "max_width_pixels": round(max_width_pixels, 4),
                "midpoint_width_pixels": round(midpoint_width_pixels, 4),
                "start_width_pixels": round(float(start_width["distance_pixels"]), 4),
                "end_width_pixels": round(float(end_width["distance_pixels"]), 4),
                "abs_delta_angle_deg": round(
                    abs(
                        float(
                            compute_line_angle_delta_deg(
                                angle_a_deg=selected_line_a["angle_deg"],
                                angle_b_deg=selected_line_b["angle_deg"],
                            )
                        )
                    ),
                    4,
                ),
                "line_a_length_pixels": round(float(selected_line_a["length_pixels"]), 4),
                "line_b_length_pixels": round(float(selected_line_b["length_pixels"]), 4),
                "line_b_start_xy": [round(float(line_b_start_xy[0]), 4), round(float(line_b_start_xy[1]), 4)],
                "line_b_end_xy": [round(float(line_b_end_xy[0]), 4), round(float(line_b_end_xy[1]), 4)],
                "line_b_midpoint_xy": [round(float(line_b_midpoint_xy[0]), 4), round(float(line_b_midpoint_xy[1]), 4)],
                "start_projection_xy": [
                    round(float(start_width["projection_x"]), 4),
                    round(float(start_width["projection_y"]), 4),
                ],
                "end_projection_xy": [
                    round(float(end_width["projection_x"]), 4),
                    round(float(end_width["projection_y"]), 4),
                ],
                "midpoint_projection_xy": [
                    round(float(midpoint_width["projection_x"]), 4),
                    round(float(midpoint_width["projection_y"]), 4),
                ],
            }
        ),
    }
