"""Point Distance 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import extract_point_from_value, measure_point_distance


NODE_TYPE_ID = "custom.opencv.point-distance"


def _read_output_metric(raw_value: object) -> str:
    """读取输出指标类型。"""

    if raw_value in {None, ""}:
        return "distance_pixels"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("output_metric 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {
        "distance_pixels",
        "manhattan_distance_pixels",
        "dx_pixels",
        "dy_pixels",
    }:
        raise InvalidRequestError(
            "output_metric 仅支持 distance_pixels、manhattan_distance_pixels、dx_pixels 或 dy_pixels"
        )
    return normalized_value


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算两点之间的距离和坐标差。"""

    point_a_payload = require_value_payload(request.input_values.get("point_a"), field_name="point_a")
    point_b_payload = require_value_payload(request.input_values.get("point_b"), field_name="point_b")
    output_metric = _read_output_metric(request.parameters.get("output_metric"))
    point_a_xy = extract_point_from_value(point_a_payload["value"], field_name="point_a")
    point_b_xy = extract_point_from_value(point_b_payload["value"], field_name="point_b")
    measurement = measure_point_distance(point_a_xy=point_a_xy, point_b_xy=point_b_xy)
    measured_value = float(measurement[output_metric])
    return {
        "value": build_value_payload(round(measured_value, 4)),
        "summary": build_value_payload(
            {
                "output_metric": output_metric,
                "point_a_xy": [round(point_a_xy[0], 4), round(point_a_xy[1], 4)],
                "point_b_xy": [round(point_b_xy[0], 4), round(point_b_xy[1], 4)],
                "dx_pixels": round(float(measurement["dx_pixels"]), 4),
                "dy_pixels": round(float(measurement["dy_pixels"]), 4),
                "distance_pixels": round(float(measurement["distance_pixels"]), 4),
                "manhattan_distance_pixels": round(float(measurement["manhattan_distance_pixels"]), 4),
                "midpoint_xy": [
                    round(float(measurement["midpoint_x"]), 4),
                    round(float(measurement["midpoint_y"]), 4),
                ],
            }
        ),
    }
