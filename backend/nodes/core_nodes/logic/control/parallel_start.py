"""Parallel 显式执行边界起点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _parallel_start_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """原样转发 Value，由输出连线数量声明实际分支数量。"""

    return {
        "value": require_value_payload(
            request.input_values.get("value"),
            field_name="value",
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.parallel-start",
        display_name="Parallel Start",
        category="logic.iteration",
        description=(
            "声明显式 Parallel 执行边界的起点。Value 可以连接任意数量的独立分支，"
            "max_concurrency 只限制同时运行的分支数。"
        ),
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
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
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "max_concurrency": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 64,
                    "default": 4,
                },
            },
        },
        capability_tags=(
            "logic.iteration",
            "parallel.boundary.start",
            "execution.pure",
        ),
    ),
    handler=_parallel_start_handler,
)
