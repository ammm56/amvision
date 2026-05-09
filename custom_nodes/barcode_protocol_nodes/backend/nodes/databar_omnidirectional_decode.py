"""DataBar Omnidirectional Decode 节点实现。"""

from __future__ import annotations

from custom_nodes.barcode_protocol_nodes.backend.support import build_decode_handler


NODE_TYPE_ID = "custom.barcode.databar-omnidirectional-decode"


handle_node = build_decode_handler(format_member_name="DataBarOmni", requested_format="DataBar Omnidirectional")
