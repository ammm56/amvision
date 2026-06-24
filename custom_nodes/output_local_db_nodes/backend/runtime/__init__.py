"""本地数据库输出 custom node runtime 入口。"""

from custom_nodes.output_local_db_nodes.backend.runtime.execution import (
    execute_local_db_upsert_node,
)

__all__ = ["execute_local_db_upsert_node"]
