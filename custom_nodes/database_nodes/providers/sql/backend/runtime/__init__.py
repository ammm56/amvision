"""本地数据库输出 custom node runtime 入口。"""

from custom_nodes.database_nodes.providers.sql.backend.runtime.execution import (
    execute_local_db_upsert_node,
)

__all__ = ["execute_local_db_upsert_node"]
