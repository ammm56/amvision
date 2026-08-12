"""Barcode decode 节点的唯一 preset registry。"""

from __future__ import annotations

from custom_nodes.barcode_nodes.specs import BarcodeNodeSpec, get_barcode_node_specs


_PRESETS_BY_NODE_TYPE_ID = {
    spec.node_type_id: spec for spec in get_barcode_node_specs()
}
if len(_PRESETS_BY_NODE_TYPE_ID) != len(get_barcode_node_specs()):
    raise RuntimeError("Barcode decode preset 存在重复 node_type_id")


def get_barcode_decode_preset(node_type_id: str) -> BarcodeNodeSpec:
    """按公开节点 ID 返回唯一 decode preset。"""

    preset = _PRESETS_BY_NODE_TYPE_ID.get(node_type_id)
    if preset is None:
        raise RuntimeError(f"未知 Barcode decode preset: {node_type_id}")
    return preset


def list_barcode_decode_presets() -> tuple[BarcodeNodeSpec, ...]:
    """按规格声明顺序返回全部 decode preset。"""

    return get_barcode_node_specs()


__all__ = ["get_barcode_decode_preset", "list_barcode_decode_presets"]
