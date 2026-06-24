"""Point To Line Distance 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.geometry import (
    extract_point_from_value,
    measure_point_to_line,
    select_line_item,
)
from custom_nodes._opencv_shared.backend.runtime.payloads import require_lines_payload
from custom_nodes._opencv_shared.backend.runtime.validators import require_positive_int


NODE_TYPE_ID = "custom.opencv.point-to-line-distance"


def _read_line_strategy(raw_value: object) -> str:
    """读取 line 选择策略。"""

    if raw_value in {None, ""}:
        return "longest"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("line_strategy 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"first", "longest", "shortest", "line-index"}:
        raise InvalidRequestError("line_strategy 不在支持的列表中")
    return normalized_value


def _read_optional_line_index(raw_value: object) -> int | None:
    """读取可选 line_index。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name="line_index")


def _read_output_metric(raw_value: object) -> str:
    """读取输出指标类型。"""

    if raw_value in {None, ""}:
        return "distance_pixels"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("output_metric 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"distance_pixels", "signed_distance_pixels"}:
        raise InvalidRequestError("output_metric 仅支持 distance_pixels 或 signed_distance_pixels")
    return normalized_value


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算单点到选中直线的距离。"""

    lines_payload = require_lines_payload(request.input_values.get("lines"))
    point_payload = require_value_payload(request.input_values.get("point"), field_name="point")
    line_strategy = _read_line_strategy(request.parameters.get("line_strategy"))
    line_index = _read_optional_line_index(request.parameters.get("line_index"))
    output_metric = _read_output_metric(request.parameters.get("output_metric"))
    selected_line = select_line_item(
        lines_payload["items"],
        strategy=line_strategy,
        line_index=line_index,
    )
    point_x, point_y = extract_point_from_value(point_payload["value"], field_name="point")
    measurement = measure_point_to_line(point_xy=(point_x, point_y), line_item=selected_line)
    signed_distance_pixels = float(measurement["signed_distance_pixels"])
    distance_pixels = float(measurement["distance_pixels"])
    measured_value = signed_distance_pixels if output_metric == "signed_distance_pixels" else distance_pixels
    return {
        "value": build_value_payload(round(measured_value, 4)),
        "summary": build_value_payload(
            {
                "line_count": len(lines_payload["items"]),
                "selected_line_index": int(selected_line["line_index"]),
                "line_strategy": line_strategy,
                "output_metric": output_metric,
                "point_xy": [round(point_x, 4), round(point_y, 4)],
                "projection_xy": [round(float(measurement["projection_x"]), 4), round(float(measurement["projection_y"]), 4)],
                "distance_pixels": round(distance_pixels, 4),
                "signed_distance_pixels": round(signed_distance_pixels, 4),
                "projection_ratio": round(float(measurement["projection_ratio"]), 6),
                "line_length_pixels": round(float(measurement["line_length_pixels"]), 4),
                "line_angle_deg": round(float(selected_line["angle_deg"]), 4),
            }
        ),
    }
