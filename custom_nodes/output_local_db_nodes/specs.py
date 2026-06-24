"""本地数据库输出节点包规格常量。"""

from __future__ import annotations


NODE_PACK_ID = "output.local-db-nodes"
NODE_PACK_VERSION = "0.1.0"

LOCAL_DB_UPSERT_NODE_TYPE_ID = "custom.output.local-db-upsert"

ALL_NODE_TYPE_IDS: tuple[str, ...] = (LOCAL_DB_UPSERT_NODE_TYPE_ID,)
