"""通用 JSON 标量转字符串节点。"""

from __future__ import annotations

import json
import math

from backend.contracts.workflows.workflow_graph import (
    NODE_CONCURRENCY_THREAD_SAFE,
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把字符串、数字或布尔值转换为稳定字符串。"""

    value = require_value_payload(
        request.input_values.get("value"),
        field_name="value",
    )["value"]
    if isinstance(value, str):
        rendered = value
    elif isinstance(value, float) and not math.isfinite(value):
        raise InvalidRequestError("Scalar To String 不支持 NaN 或 Infinity")
    elif isinstance(value, (bool, int, float)):
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    else:
        raise InvalidRequestError(
            "Scalar To String 只支持字符串、数字或布尔值",
            details={"value_type": type(value).__name__},
        )
    return {"value": build_value_payload(rendered)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.scalar-to-string",
        display_name="Scalar To String",
        category="core.logic.transform",
        description="显式把 JSON 字符串、有限数字或布尔值转换为稳定字符串；拒绝 null、对象和数组。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        concurrency_policy=NODE_CONCURRENCY_THREAD_SAFE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="value",
                display_name="String",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        capability_tags=("logic.convert", "string.convert", "execution.pure"),
    ),
    handler=_handler,
)
