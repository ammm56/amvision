"""真正控制图执行路径的 Conditional 终点。"""

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


def _conditional_end_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """阻止 End 绕过 Graph Executor 的互斥分支路径。"""

    raise ServiceConfigurationError(
        "Conditional End 必须由 WorkflowGraphExecutor 的选择边界处理",
        details={"node_id": request.node_id},
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.conditional-end",
        display_name="Conditional End",
        category="core.logic.branch",
        description="合并 Conditional Start 选中的唯一分支结果。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="value.v1",
                multiple=True,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="selected_branch",
                display_name="Selected Branch",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=(
            "logic.branch",
            "conditional.boundary.end",
            "execution.control-flow",
        ),
    ),
    handler=_conditional_end_handler,
)
