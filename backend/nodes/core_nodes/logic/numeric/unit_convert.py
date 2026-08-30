"""同量纲数值单位转换节点。"""

from __future__ import annotations

import math

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.logic.numeric._common import require_finite_number
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


UNIT_DEFINITIONS: dict[str, tuple[str, float]] = {
    "millimeter": ("length", 0.001),
    "centimeter": ("length", 0.01),
    "meter": ("length", 1.0),
    "inch": ("length", 0.0254),
    "degree": ("angle", math.pi / 180.0),
    "radian": ("angle", 1.0),
    "millisecond": ("time", 0.001),
    "second": ("time", 1.0),
    "minute": ("time", 60.0),
}


def _unit_convert_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """在同量纲的登记单位之间转换有限数值。"""

    raw_value = require_value_payload(
        request.input_values.get("value"),
        field_name="value",
    )["value"]
    value = require_finite_number(raw_value, field_name="value")
    source_unit = _require_unit(
        request.parameters.get("source_unit", "millimeter"),
        "source_unit",
    )
    target_unit = _require_unit(
        request.parameters.get("target_unit", "meter"),
        "target_unit",
    )
    source_dimension, source_factor = UNIT_DEFINITIONS[source_unit]
    target_dimension, target_factor = UNIT_DEFINITIONS[target_unit]
    if source_dimension != target_dimension:
        raise InvalidRequestError("Unit Convert 不允许跨量纲转换")
    converted_value = require_finite_number(
        value * source_factor / target_factor,
        field_name="converted_value",
    )
    return {
        "value": build_value_payload(converted_value),
        "summary": build_value_payload(
            {
                "source_unit": source_unit,
                "target_unit": target_unit,
                "dimension": source_dimension,
                "source_value": value,
                "converted_value": converted_value,
            }
        ),
    }


def _require_unit(raw_value: object, field_name: str) -> str:
    """读取已登记单位名称。"""

    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in UNIT_DEFINITIONS:
        raise InvalidRequestError(f"{field_name} 不是已登记单位")
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.unit-convert",
        display_name="Unit Convert",
        category="core.logic.transform",
        description="在已登记的长度、角度或时间单位之间转换，不处理 Pixel-to-World。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(name="value", display_name="Value", payload_type_id="value.v1"),
        ),
        output_ports=(
            NodePortDefinition(name="value", display_name="Value", payload_type_id="value.v1"),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "source_unit": {
                    "type": "string",
                    "enum": sorted(UNIT_DEFINITIONS),
                    "default": "millimeter",
                },
                "target_unit": {
                    "type": "string",
                    "enum": sorted(UNIT_DEFINITIONS),
                    "default": "meter",
                },
            },
            "required": ["source_unit", "target_unit"],
        },
        capability_tags=("logic.numeric", "unit.convert", "execution.pure"),
    ),
    handler=_unit_convert_handler,
)
