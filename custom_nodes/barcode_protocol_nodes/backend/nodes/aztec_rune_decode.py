"""Aztec Rune Decode 节点实现。"""

from __future__ import annotations

from custom_nodes.barcode_protocol_nodes.backend.support import build_decode_handler


NODE_TYPE_ID = "custom.barcode.aztec-rune-decode"


handle_node = build_decode_handler(format_member_name="AztecRune", requested_format="Aztec Rune")
