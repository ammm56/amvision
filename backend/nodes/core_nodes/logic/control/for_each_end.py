"""for-each 循环结束节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _for_each_end_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """阻止循环边界节点走普通节点执行路径。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：当前函数不会正常返回。
    """

    raise ServiceConfigurationError(
        "for-each end 节点必须由 WorkflowGraphExecutor 的循环边界路径处理",
        details={"node_id": request.node_id},
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.for-each-end",
        display_name="For Each End",
        category="logic.iteration",
        description="声明循环结束边界。每轮循环把 result 输入收集到 results 输出列表中。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
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
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("logic.iteration", "loop.for-each", "loop.boundary.end"),
    ),
    handler=_for_each_end_handler,
)
