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

    assert build_custom_node_catalog_payload(workflow_dir=workflow_dir) == expected_catalog_payload


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