"""通用 Modbus 写值节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime import execute_write_value_node
from custom_nodes.plc_modbus_tcp_nodes.specs import WRITE_VALUE_NODE_TYPE_ID


NODE_TYPE_ID = WRITE_VALUE_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行通用 Modbus 写值。"""

    return execute_write_value_node(
        request=request,
        node_name="write-value",
    )
