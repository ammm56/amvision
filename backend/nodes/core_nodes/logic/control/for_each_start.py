"""for-each 循环开始节点。"""

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


def _for_each_start_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """阻止循环边界节点走普通节点执行路径。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：当前函数不会正常返回。
    """

    raise ServiceConfigurationError(
        "for-each start 节点必须由 WorkflowGraphExecutor 的循环边界路径处理",
        details={"node_id": request.node_id},
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.for-each-start",
        display_name="For Each Start",
        category="logic.iteration",
        description="声明循环开始边界。items 输入中的每一项会依次从 item 输出流入后续节点，index 输出当前序号。",
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
                name="item",
                display_name="Item",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="index",
                display_name="Index",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("logic.iteration", "loop.for-each", "loop.boundary.start"),
    ),
    handler=_for_each_start_handler,
)
