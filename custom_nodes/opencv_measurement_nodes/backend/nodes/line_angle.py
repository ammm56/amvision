"""Line Angle 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    require_lines_payload,
    require_number,
    require_positive_int,
    select_line_item,
)


NODE_TYPE_ID = "custom.opencv.line-angle"


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


def _read_optional_reference_angle(raw_value: object) -> float | None:
    """读取可选参考角度。"""

    if raw_value in {None, ""}:
        return None
    return float(require_number(raw_value, field_name="reference_angle_deg"))


def _read_output_metric(raw_value: object, *, reference_angle_deg: float | None) -> str:
    """读取输出指标类型。"""

    if raw_value in {None, ""}:
        return "delta_angle_deg" if reference_angle_deg is not None else "angle_deg"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("output_metric 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"angle_deg", "abs_angle_deg", "delta_angle_deg"}:
        raise InvalidRequestError("output_metric 仅支持 angle_deg、abs_angle_deg 或 delta_angle_deg")
    if normalized_value == "delta_angle_deg" and reference_angle_deg is None:
        raise InvalidRequestError("output_metric 为 delta_angle_deg 时必须提供 reference_angle_deg")
    return normalized_value


def _normalize_reference_delta(angle_deg: float, reference_angle_deg: float) -> float:
    """计算无方向语义下的最小角度偏差。"""

    delta_angle = abs(float(angle_deg - reference_angle_deg)) % 180.0
    if delta_angle > 90.0:
        delta_angle = 180.0 - delta_angle
    return round(float(delta_angle), 4)


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """读取选中直线的方向角或相对角度偏差。"""

    lines_payload = require_lines_payload(request.input_values.get("lines"))
    line_strategy = _read_line_strategy(request.parameters.get("line_strategy"))
    line_index = _read_optional_line_index(request.parameters.get("line_index"))
    reference_angle_deg = _read_optional_reference_angle(request.parameters.get("reference_angle_deg"))
    output_metric = _read_output_metric(
        request.parameters.get("output_metric"),
        reference_angle_deg=reference_angle_deg,
    )
    selected_line = select_line_item(
        lines_payload["items"],
        strategy=line_strategy,
        line_index=line_index,
    )
    angle_deg = round(float(selected_line["angle_deg"]), 4)
    abs_angle_deg = round(abs(angle_deg), 4)
    delta_angle_deg = (
        _normalize_reference_delta(angle_deg, reference_angle_deg)
        if reference_angle_deg is not None
        else None
    )
    measured_value = {
        "angle_deg": angle_deg,
        "abs_angle_deg": abs_angle_deg,
        "delta_angle_deg": delta_angle_deg,
    }[output_metric]
    if measured_value is None:
        raise InvalidRequestError("当前输出指标缺少参考角度")
    return {
        "value": build_value_payload(round(float(measured_value), 4)),
        "summary": build_value_payload(
            {
                "line_count": len(lines_payload["items"]),
                "selected_line_index": int(selected_line["line_index"]),
                "line_strategy": line_strategy,
                "output_metric": output_metric,
                "angle_deg": angle_deg,
                "abs_angle_deg": abs_angle_deg,
                "reference_angle_deg": round(reference_angle_deg, 4) if reference_angle_deg is not None else None,
                "delta_angle_deg": delta_angle_deg,
                "line_length_pixels": round(float(selected_line["length_pixels"]), 4),
            }
        ),
    }
