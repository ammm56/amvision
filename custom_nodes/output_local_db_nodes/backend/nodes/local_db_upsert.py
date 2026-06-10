"""本地数据库 upsert 节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.output_local_db_nodes.backend.nodes._runtime import execute_local_db_upsert_node
from custom_nodes.output_local_db_nodes.specs import LOCAL_DB_UPSERT_NODE_TYPE_ID


NODE_TYPE_ID = LOCAL_DB_UPSERT_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行第一阶段受限本地数据库 upsert。"""

    return execute_local_db_upsert_node(
        request=request,
        node_name="local-db-upsert",
    )
