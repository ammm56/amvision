"""Circle Diameter 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    require_circles_payload,
    require_positive_int,
    select_circle_item,
)


NODE_TYPE_ID = "custom.opencv.circle-diameter"


def _read_circle_strategy(raw_value: object) -> str:
    """读取 circle 选择策略。"""

    if raw_value in {None, ""}:
        return "largest"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("circle_strategy 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"first", "largest", "smallest", "circle-index"}:
        raise InvalidRequestError("circle_strategy 不在支持的列表中")
    return normalized_value


def _read_optional_circle_index(raw_value: object) -> int | None:
    """读取可选 circle_index。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name="circle_index")


def _read_output_metric(raw_value: object) -> str:
    """读取输出指标类型。"""

    if raw_value in {None, ""}:
        return "diameter"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("output_metric 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"diameter", "radius", "area", "circumference"}:
        raise InvalidRequestError("output_metric 仅支持 diameter、radius、area 或 circumference")
    return normalized_value


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """读取选中圆的直径 / 半径 / 面积指标。"""

    circles_payload = require_circles_payload(request.input_values.get("circles"))
    circle_strategy = _read_circle_strategy(request.parameters.get("circle_strategy"))
    circle_index = _read_optional_circle_index(request.parameters.get("circle_index"))
    output_metric = _read_output_metric(request.parameters.get("output_metric"))
    selected_circle = select_circle_item(
        circles_payload["items"],
        strategy=circle_strategy,
        circle_index=circle_index,
    )
    measured_value = {
        "diameter": float(selected_circle["diameter"]),
        "radius": float(selected_circle["radius"]),
        "area": float(selected_circle["area"]),
        "circumference": float(selected_circle.get("circumference", 0.0)),
    }[output_metric]
    return {
        "value": build_value_payload(round(measured_value, 4)),
        "summary": build_value_payload(
            {
                "circle_count": len(circles_payload["items"]),
                "selected_circle_index": int(selected_circle["circle_index"]),
                "circle_strategy": circle_strategy,
                "output_metric": output_metric,
                "diameter": round(float(selected_circle["diameter"]), 4),
                "radius": round(float(selected_circle["radius"]), 4),
                "area": round(float(selected_circle["area"]), 4),
                "circumference": round(float(selected_circle.get("circumference", 0.0)), 4),
                "center_xy": list(selected_circle["center_xy"]),
                "fill_ratio": round(float(selected_circle.get("fill_ratio", 0.0)), 4)
                if "fill_ratio" in selected_circle
                else None,
            }
        ),
    }
