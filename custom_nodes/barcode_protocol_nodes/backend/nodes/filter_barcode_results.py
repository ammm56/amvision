"""Barcode 结果过滤节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.barcode_protocol_nodes.backend.support import filter_barcode_results_payload
from custom_nodes.barcode_protocol_nodes.specs import NODE_PACK_ID, NODE_PACK_VERSION


NODE_TYPE_ID = "custom.barcode.filter-results"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按指定条件过滤条码结果。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含过滤后 barcode-results.v1 的节点输出。
    """

    return {
        "results": filter_barcode_results_payload(
            request.input_values.get("results"),
            parameters=request.parameters,
        )
    }