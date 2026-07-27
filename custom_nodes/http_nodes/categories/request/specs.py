"""HTTP Request 节点规格常量。"""

from __future__ import annotations


NODE_PACK_ID = "http.nodes"
NODE_PACK_VERSION = "0.2.0"

HTTP_REQUEST_NODE_TYPE_ID = "custom.http.request"

ALL_NODE_TYPE_IDS: tuple[str, ...] = (HTTP_REQUEST_NODE_TYPE_ID,)
