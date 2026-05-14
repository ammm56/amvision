"""core payload contract 回归测试。"""

from __future__ import annotations

from backend.nodes.core_catalog import get_core_workflow_payload_contracts


def test_core_payload_contracts_include_image_base64_and_local_buffer_image_refs() -> None:
    """验证 core payload contracts 已收敛到 base64 输入和 LocalBufferBroker 图片引用。"""

    payload_contracts = {
        item.payload_type_id: item
        for item in get_core_workflow_payload_contracts()
    }

    assert "image-base64.v1" in payload_contracts

    image_ref_contract = payload_contracts["image-ref.v1"]
    image_ref_schema = image_ref_contract.json_schema
    assert image_ref_contract.transport_kind == "hybrid"
    assert image_ref_schema["required"] == ["transport_kind", "media_type"]
    assert image_ref_schema["properties"]["transport_kind"]["enum"] == [
        "memory",
        "storage",
        "buffer",
        "frame",
    ]
    assert "buffer_ref" in image_ref_schema["properties"]
    assert "frame_ref" in image_ref_schema["properties"]

    image_base64_contract = payload_contracts["image-base64.v1"]
    assert image_base64_contract.transport_kind == "inline-json"
    assert image_base64_contract.json_schema["required"] == ["image_base64"]

    image_refs_contract = payload_contracts["image-refs.v1"]
    item_schema = image_refs_contract.json_schema["properties"]["items"]["items"]
    assert item_schema["required"] == ["transport_kind", "media_type"]
    assert item_schema["properties"]["transport_kind"]["enum"] == [
        "memory",
        "storage",
        "buffer",
        "frame",
    ]
    assert "source_image" in image_refs_contract.json_schema["properties"]