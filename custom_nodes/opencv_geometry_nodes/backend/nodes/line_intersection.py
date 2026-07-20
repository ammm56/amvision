"""Line Intersection 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.parameter_utils import is_empty_parameter
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.line_geometry import line_intersection, select_line
from custom_nodes._opencv_shared.backend.runtime.payloads import require_lines_payload


NODE_TYPE_ID = "custom.opencv.line-intersection"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按显式 index 计算两个 lines.v1 输入的无限直线交点。"""

    first_payload = require_lines_payload(request.input_values.get("first_lines"))
    second_payload = require_lines_payload(request.input_values.get("second_lines"))
    _require_same_source(first_payload, second_payload)
    first_index = _read_positive_int(request.parameters.get("first_line_index"), "first_line_index")
    second_index = _read_positive_int(request.parameters.get("second_line_index"), "second_line_index")
    first_line = select_line(first_payload["items"], one_based_index=first_index, field_name="first_line_index")
    second_line = select_line(
        second_payload["items"],
        one_based_index=second_index,
        field_name="second_line_index",
    )
    point_xy = line_intersection(first_line, second_line)
    return {
        "point": build_value_payload({"point_xy": point_xy}),
        "summary": build_value_payload(
            {
                "point_xy": point_xy,
                "first_line_index": first_index,
                "second_line_index": second_index,
                "source_object_key": first_payload.get("source_object_key")
                or second_payload.get("source_object_key"),
            }
        ),
    }


def _read_positive_int(raw_value: object, field_name: str) -> int:
    """读取一基 line index。"""

    if is_empty_parameter(raw_value):
        return 1
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 1:
        raise InvalidRequestError(f"{field_name} 必须是正整数")
    return raw_value


def _require_same_source(first_payload: dict[str, object], second_payload: dict[str, object]) -> None:
    """存在 source key 时校验两个 line 输入来自同一张图。"""

    first_key = first_payload.get("source_object_key")
    second_key = second_payload.get("source_object_key")
    if isinstance(first_key, str) and isinstance(second_key, str) and first_key != second_key:
        raise InvalidRequestError("Line Intersection 的两个输入必须来自同一张图片")
