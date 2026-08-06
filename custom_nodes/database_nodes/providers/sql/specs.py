"""Database SQL 节点规格常量。"""

from __future__ import annotations


NODE_PACK_ID = "database.nodes"
NODE_PACK_VERSION = "0.1.3"

SQL_UPSERT_NODE_TYPE_ID = "custom.database.sql.upsert"

ALL_NODE_TYPE_IDS: tuple[str, ...] = (SQL_UPSERT_NODE_TYPE_ID,)
