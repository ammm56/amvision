"""PZN Decode 节点实现。"""

from __future__ import annotations

from custom_nodes.barcode_nodes.shared.backend.runtime.decode import build_registered_decode_handler


NODE_TYPE_ID = "custom.barcode.pzn-decode"


handle_node = build_registered_decode_handler(node_type_id=NODE_TYPE_ID)
