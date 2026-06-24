"""Modbus wait-condition 节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime import (
    execute_wait_condition_node,
)
from custom_nodes.plc_modbus_tcp_nodes.specs import WAIT_CONDITION_NODE_TYPE_ID


NODE_TYPE_ID = WAIT_CONDITION_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 Modbus wait-condition。"""

    return execute_wait_condition_node(
        request=request,
        node_name="wait-condition",
    )
