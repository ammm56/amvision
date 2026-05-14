"""Code 32 Decode 节点实现。"""

from __future__ import annotations

from custom_nodes.barcode_protocol_nodes.backend.support import build_decode_handler


NODE_TYPE_ID = "custom.barcode.code32-decode"


handle_node = build_decode_handler(format_member_name="Code32", requested_format="Code 32")
