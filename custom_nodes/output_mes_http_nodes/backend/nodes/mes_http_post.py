"""MES HTTP 结果回传节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.output_mes_http_nodes.backend.nodes._runtime import execute_mes_http_post_node
from custom_nodes.output_mes_http_nodes.specs import MES_HTTP_POST_NODE_TYPE_ID


NODE_TYPE_ID = MES_HTTP_POST_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行第一阶段受限 MES HTTP 输出。"""

    return execute_mes_http_post_node(
        request=request,
        node_name="mes-http-post",
    )
