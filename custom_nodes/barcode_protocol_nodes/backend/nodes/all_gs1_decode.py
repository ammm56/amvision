"""Decode All GS1 Barcodes 节点实现。"""

from __future__ import annotations

from custom_nodes.barcode_protocol_nodes.backend.support import build_decode_handler


NODE_TYPE_ID = "custom.barcode.all-gs1-decode"


handle_node = build_decode_handler(format_member_name="AllGS1", requested_format="All GS1")
