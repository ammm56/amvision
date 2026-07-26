"""MES HTTP 输出节点包规格常量。"""

from __future__ import annotations


NODE_PACK_ID = "http.nodes"
NODE_PACK_VERSION = "0.2.0"

HTTP_REQUEST_NODE_TYPE_ID = "custom.http.request"
MES_HTTP_POST_NODE_TYPE_ID = "custom.output.mes-http-post"

ALL_NODE_TYPE_IDS: tuple[str, ...] = (
    HTTP_REQUEST_NODE_TYPE_ID,
    MES_HTTP_POST_NODE_TYPE_ID,
)
