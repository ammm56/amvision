"""Barcode 结果判断节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.barcode_protocol_nodes.backend.support import filter_barcode_results_payload
from custom_nodes.barcode_protocol_nodes.specs import NODE_PACK_ID, NODE_PACK_VERSION


NODE_TYPE_ID = "custom.barcode.match-exists"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """判断条码结果中是否存在符合条件的匹配项。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含布尔结果和匹配数量的节点输出。
    """

    filtered_results = filter_barcode_results_payload(
        request.input_values.get("results"),
        parameters=request.parameters,
    )
    matched_count = int(filtered_results.get("count", 0))
    return {
        "result": {"value": matched_count > 0},
        "count": {"value": matched_count},
    }