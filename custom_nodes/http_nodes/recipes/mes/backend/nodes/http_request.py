"""通用 HTTP 请求节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.http_nodes.recipes.mes.backend.runtime import (
    execute_mes_http_post_node,
)
from custom_nodes.http_nodes.recipes.mes.specs import HTTP_REQUEST_NODE_TYPE_ID


NODE_TYPE_ID = HTTP_REQUEST_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行受限的通用 HTTP JSON 请求。"""

    return execute_mes_http_post_node(
        request=request,
        node_name="http-request",
    )
