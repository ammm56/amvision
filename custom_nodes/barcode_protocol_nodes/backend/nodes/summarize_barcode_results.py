"""Barcode 结果摘要节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.barcode_protocol_nodes.backend.support import build_barcode_results_summary
from custom_nodes.barcode_protocol_nodes.specs import NODE_PACK_ID, NODE_PACK_VERSION


NODE_TYPE_ID = "custom.barcode.results-summary"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """输出条码结果的轻量摘要对象。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含 response-body.v1 摘要的节点输出。
    """

    return {"body": build_barcode_results_summary(request.input_values.get("results"))}