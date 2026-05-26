"""for-each 循环逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _for_each_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """声明 for-each 节点必须由图执行器的特殊路径执行。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：当前函数不会正常返回。
    """

    raise ServiceConfigurationError(
        "for-each 节点必须由 WorkflowGraphExecutor 特殊执行路径处理",
        details={"node_id": request.node_id},
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.for-each",
        display_name="For Each",
        category="logic.iteration",
        description="按给定 body_node_ids 逐项执行循环体，并收集指定 result_node_id.result_port 的结果列表；循环体内的 loop-control 节点可触发 break/continue。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="items",
                display_name="Items",
                payload_type_id="value.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="results",
                display_name="Results",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="count",
                display_name="Count",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="terminated_early",
                display_name="Terminated Early",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="termination_reason",
                display_name="Termination Reason",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="termination_index",
                display_name="Termination Index",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "body_node_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "result_node_id": {"type": "string"},
                "result_port": {"type": "string"},
                "item_variable_name": {"type": "string"},
                "index_variable_name": {"type": "string"},
            },
            "required": ["body_node_ids", "result_node_id", "result_port"],
        },
        capability_tags=("logic.iteration", "loop.for-each"),
    ),
    handler=_for_each_handler,
)