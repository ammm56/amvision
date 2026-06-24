"""Modbus 结果回写节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime import (
    execute_write_result_signals_node,
)
from custom_nodes.plc_modbus_tcp_nodes.specs import WRITE_RESULT_SIGNALS_NODE_TYPE_ID


NODE_TYPE_ID = WRITE_RESULT_SIGNALS_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 Modbus 结果回写。"""

    return execute_write_result_signals_node(
        request=request,
        node_name="write-result-signals",
    )
