"""Barcode results 转 value 节点。"""

from __future__ import annotations

from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_TYPE_ID = "custom.barcode.results-to-value"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 barcode-results.v1 包装成 value.v1。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包装后的 value payload。
    """

    raw_payload = request.input_values.get("results")
    if not isinstance(raw_payload, dict):
        raise InvalidRequestError(
            "barcode results-to-value 节点要求 results payload 必须是对象",
            details={"node_id": request.node_id},
        )
    return {"value": build_value_payload(dict(raw_payload))}