"""MicroPDF417 Decode 节点实现。"""

from __future__ import annotations

from custom_nodes.barcode_protocol_nodes.backend.support import build_decode_handler


NODE_TYPE_ID = "custom.barcode.micro-pdf417-decode"


handle_node = build_decode_handler(format_member_name="MicroPDF417", requested_format="MicroPDF417")
