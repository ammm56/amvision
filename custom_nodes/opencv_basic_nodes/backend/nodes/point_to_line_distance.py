"""Point To Line Distance 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    normalize_point_xy,
    require_lines_payload,
    require_positive_int,
    select_line_item,
)


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


def _extract_point_xy(raw_value: object) -> tuple[float, float]:
    """从 value.v1 中解析单个点坐标。"""

    if isinstance(raw_value, (list, tuple)):
        return normalize_point_xy(raw_value, field_name="point")
    if isinstance(raw_value, dict):
        if "point_xy" in raw_value:
            return normalize_point_xy(raw_value.get("point_xy"), field_name="point_xy")
        if "center_xy" in raw_value:
            return normalize_point_xy(raw_value.get("center_xy"), field_name="center_xy")
        if "x" in raw_value and "y" in raw_value:
            return (
                float(raw_value["x"]) if isinstance(raw_value["x"], (int, float)) and not isinstance(raw_value["x"], bool) else _raise_invalid_point(),
                float(raw_value["y"]) if isinstance(raw_value["y"], (int, float)) and not isinstance(raw_value["y"], bool) else _raise_invalid_point(),
            )
    raise InvalidRequestError("point 输入必须是 [x, y]、{point_xy:[x,y]}、{center_xy:[x,y]} 或 {x, y}")


def _raise_invalid_point() -> float:
    """统一抛出点坐标格式错误。"""

    raise InvalidRequestError("point 输入中的坐标必须是数值")


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
    point_x, point_y = _extract_point_xy(point_payload["value"])
    start_x, start_y = normalize_point_xy(selected_line["start_xy"], field_name="start_xy")
    end_x, end_y = normalize_point_xy(selected_line["end_xy"], field_name="end_xy")
    line_dx = float(end_x - start_x)
    line_dy = float(end_y - start_y)
    line_length = float(math.hypot(line_dx, line_dy))
    if line_length <= 0:
        raise InvalidRequestError("选中的 line 长度必须大于 0")
    relative_dx = float(point_x - start_x)
    relative_dy = float(point_y - start_y)
    signed_distance_pixels = float((relative_dx * line_dy - relative_dy * line_dx) / line_length)
    distance_pixels = float(abs(signed_distance_pixels))
    projection_ratio = float((relative_dx * line_dx + relative_dy * line_dy) / (line_length * line_length))
    projection_x = float(start_x + projection_ratio * line_dx)
    projection_y = float(start_y + projection_ratio * line_dy)
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
                "projection_xy": [round(projection_x, 4), round(projection_y, 4)],
                "distance_pixels": round(distance_pixels, 4),
                "signed_distance_pixels": round(signed_distance_pixels, 4),
                "projection_ratio": round(projection_ratio, 6),
                "line_length_pixels": round(line_length, 4),
                "line_angle_deg": round(float(selected_line["angle_deg"]), 4),
            }
        ),
    }
