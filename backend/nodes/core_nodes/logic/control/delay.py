"""可取消且受 Workflow deadline 限制的延时节点。"""

from __future__ import annotations

import math

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


MAX_DELAY_SECONDS = 86400.0


def _delay_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行可中断等待并原样转发可选值。"""

    seconds = _require_delay_seconds(request.parameters.get("seconds", 0.0))
    build_node_execution_control(request).wait_interruptibly(seconds)
    raw_value = request.input_values.get("value")
    value_payload = (
        require_value_payload(raw_value, field_name="value")
        if raw_value is not None
        else build_value_payload(None)
    )
    return {
        "value": value_payload,
        "elapsed_seconds": build_value_payload(seconds),
    }


def _require_delay_seconds(raw_value: object) -> float:
    """读取有界有限延时。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
        raise InvalidRequestError("Delay 的 seconds 必须是数值")
    normalized_value = float(raw_value)
    if not math.isfinite(normalized_value):
        raise InvalidRequestError("Delay 的 seconds 必须是有限数值")
    if not 0.0 <= normalized_value <= MAX_DELAY_SECONDS:
        raise InvalidRequestError("Delay 的 seconds 必须在 0 到 86400 之间")
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.delay",
        display_name="Delay",
        category="core.logic.iteration",
        description="等待指定秒数并响应取消和 Workflow deadline，不使用不可中断 sleep。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(name="value", display_name="Value", payload_type_id="value.v1"),
            NodePortDefinition(
                name="elapsed_seconds",
                display_name="Elapsed Seconds",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": MAX_DELAY_SECONDS,
                    "default": 0.0,
                    "title": "Seconds",
                }
            },
        },
        capability_tags=("logic.delay", "execution.cancellable"),
    ),
    handler=_delay_handler,
)
