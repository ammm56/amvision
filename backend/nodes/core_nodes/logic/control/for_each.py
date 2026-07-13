"""for-each 循环逻辑节点。"""

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
        description="按输入 items 逐项执行循环体，并收集指定节点端口的结果列表；适合逐图推理、逐 ROI 检查和逐项规则判断。",
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
                    "title": "Loop Body Nodes",
                    "description": "循环体中的节点 id 列表。运行时会按图中的拓扑顺序执行这些节点，不按数组书写顺序强制执行。",
                },
                "result_node_id": {
                    "type": "string",
                    "title": "Collect Result Node",
                    "description": "每轮循环结束时用于收集结果的节点 id，必须属于 Loop Body Nodes。",
                },
                "result_port": {
                    "type": "string",
                    "title": "Collect Result Port",
                    "description": "每轮循环从 Collect Result Node 的哪个输出端口收集结果。",
                },
                "item_variable_name": {
                    "type": "string",
                    "default": "item",
                    "title": "Item Variable",
                    "description": "当前循环项写入的变量名，循环体内用 Get Variable 按这个名称读取。",
                },
                "index_variable_name": {
                    "type": "string",
                    "default": "index",
                    "title": "Index Variable",
                    "description": "当前循环序号写入的变量名，循环体内用 Get Variable 按这个名称读取，序号从 0 开始。",
                },
            },
            "required": ["body_node_ids", "result_node_id", "result_port"],
        },
        capability_tags=("logic.iteration", "loop.for-each"),
    ),
    handler=_for_each_handler,
)
