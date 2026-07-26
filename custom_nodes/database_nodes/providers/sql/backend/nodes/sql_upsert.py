"""通用 SQL upsert 节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.database_nodes.providers.sql.backend.runtime import (
    execute_local_db_upsert_node,
)
from custom_nodes.database_nodes.providers.sql.specs import SQL_UPSERT_NODE_TYPE_ID


NODE_TYPE_ID = SQL_UPSERT_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行受限的 SQL 单表 upsert。"""

    return execute_local_db_upsert_node(
        request=request,
        node_name="sql-upsert",
    )
