"""通用 Modbus 读值节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime import execute_read_value_node
from custom_nodes.plc_modbus_tcp_nodes.specs import READ_VALUE_NODE_TYPE_ID


NODE_TYPE_ID = READ_VALUE_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行通用 Modbus 读值。"""

    return execute_read_value_node(
        request=request,
        node_name="read-value",
    )
