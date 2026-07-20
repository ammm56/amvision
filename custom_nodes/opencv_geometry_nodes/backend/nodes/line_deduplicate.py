"""Line Deduplicate 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.parameter_utils import is_empty_parameter
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.line_geometry import deduplicate_lines
from custom_nodes._opencv_shared.backend.runtime.payloads import build_lines_payload, require_lines_payload
from custom_nodes._opencv_shared.backend.runtime.performance import read_find_result_limit


NODE_TYPE_ID = "custom.opencv.line-deduplicate"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对任意 lines.v1 输入执行稳定去重和有界截断。"""

    lines_payload = require_lines_payload(request.input_values.get("lines"))
    angle_tolerance_deg = _read_non_negative_float(
        request.parameters.get("angle_tolerance_deg"),
        field_name="angle_tolerance_deg",
        default_value=2.0,
    )
    if angle_tolerance_deg > 90:
        raise InvalidRequestError("angle_tolerance_deg 不能大于 90")
    distance_tolerance_pixels = _read_non_negative_float(
        request.parameters.get("distance_tolerance_pixels"),
        field_name="distance_tolerance_pixels",
        default_value=4.0,
    )
    limit = read_find_result_limit(request.parameters.get("limit"))
    deduplicated_items = deduplicate_lines(
        list(lines_payload["items"]),
        angle_tolerance_deg=angle_tolerance_deg,
        distance_tolerance_pixels=distance_tolerance_pixels,
    )[:limit]
    for line_index, line_item in enumerate(deduplicated_items, start=1):
        line_item["line_index"] = line_index
    return {
        "lines": build_lines_payload(
            items=deduplicated_items,
            source_image=lines_payload.get("source_image"),
            source_object_key=lines_payload.get("source_object_key"),
        ),
        "summary": build_value_payload(
            {
                "input_count": len(lines_payload["items"]),
                "output_count": len(deduplicated_items),
                "angle_tolerance_deg": angle_tolerance_deg,
                "distance_tolerance_pixels": distance_tolerance_pixels,
                "limit": limit,
            }
        ),
    }


def _read_non_negative_float(
    raw_value: object,
    *,
    field_name: str,
    default_value: float,
) -> float:
    """读取非负浮点参数。"""

    if is_empty_parameter(raw_value):
        return default_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    value = float(raw_value)
    if value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return value
