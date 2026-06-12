"""MES HTTP 输出节点包规格常量。"""

from __future__ import annotations


NODE_PACK_ID = "output.mes-http-nodes"
NODE_PACK_VERSION = "0.1.0"

MES_HTTP_POST_NODE_TYPE_ID = "custom.output.mes-http-post"

ALL_NODE_TYPE_IDS: tuple[str, ...] = (
    MES_HTTP_POST_NODE_TYPE_ID,
)
