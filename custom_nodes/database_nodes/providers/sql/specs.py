"""本地数据库输出节点包规格常量。"""

from __future__ import annotations


NODE_PACK_ID = "database.nodes"
NODE_PACK_VERSION = "0.2.0"

SQL_UPSERT_NODE_TYPE_ID = "custom.database.sql.upsert"
LOCAL_DB_UPSERT_NODE_TYPE_ID = "custom.output.local-db-upsert"

ALL_NODE_TYPE_IDS: tuple[str, ...] = (
    SQL_UPSERT_NODE_TYPE_ID,
    LOCAL_DB_UPSERT_NODE_TYPE_ID,
)
