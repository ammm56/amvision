"""Barcode/QR 协议节点目录生成测试。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from custom_nodes.barcode_protocol_nodes.workflow.catalog_builder import build_custom_node_catalog_payload


def test_barcode_protocol_node_catalog_builder_matches_checked_in_catalog() -> None:
    """验证 builder 生成结果与仓库内 catalog.json 保持一致。"""

    repository_root = Path(__file__).resolve().parents[1]
    workflow_dir = repository_root / "custom_nodes" / "barcode_protocol_nodes" / "workflow"
    expected_catalog_payload = json.loads((workflow_dir / "catalog.json").read_text(encoding="utf-8"))
    actual_catalog_payload = build_custom_node_catalog_payload(workflow_dir=workflow_dir)

    assert actual_catalog_payload == expected_catalog_payload
    _assert_source_image_schema_supports_local_buffer_refs(catalog_payload=actual_catalog_payload)


def test_barcode_protocol_node_catalog_builder_rejects_non_object_node_fragment(tmp_path: Path) -> None:
    """验证 builder 会拒绝非对象结构的节点目录碎片。"""

    repository_root = Path(__file__).resolve().parents[1]
    source_workflow_dir = repository_root / "custom_nodes" / "barcode_protocol_nodes" / "workflow"
    workflow_dir = tmp_path / "workflow"
    shutil.copytree(source_workflow_dir, workflow_dir)
    node_fragment_path = workflow_dir / "catalog_sources" / "nodes" / "code128_decode.json"
    node_fragment_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="节点目录碎片必须是对象"):
        build_custom_node_catalog_payload(workflow_dir=workflow_dir)


def _assert_source_image_schema_supports_local_buffer_refs(*, catalog_payload: dict[str, object]) -> None:
    """验证 barcode-results source_image schema 支持 LocalBufferBroker 引用。

    参数：
    - catalog_payload：custom node catalog JSON。
    """

    payload_contracts = catalog_payload["payload_contracts"]
    assert isinstance(payload_contracts, list)
    contract_payload = next(
        contract for contract in payload_contracts if contract["payload_type_id"] == "barcode-results.v1"
    )
    source_image_schema = contract_payload["json_schema"]["properties"]["source_image"]
    transport_enum = set(source_image_schema["properties"]["transport_kind"]["enum"])
    requirements_by_kind = {
        branch["properties"]["transport_kind"]["const"]: set(branch["required"])
        for branch in source_image_schema["oneOf"]
    }

    assert {"memory", "storage", "buffer", "frame"} <= transport_enum
    assert "buffer_ref" in source_image_schema["properties"]
    assert "frame_ref" in source_image_schema["properties"]
    assert requirements_by_kind["buffer"] == {"buffer_ref"}
    assert requirements_by_kind["frame"] == {"frame_ref"}