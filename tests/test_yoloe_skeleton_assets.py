"""YOLOE 与 SAM3 资产骨架和节点包骨架校验。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.nodes.node_pack_manifest import CustomNodeCatalogDocument, NodePackManifest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_yoloe_node_pack_manifest_and_catalog_are_valid() -> None:
    """验证 YOLOE 节点包 manifest 与 catalog 可以按当前协议解析。"""

    manifest_path = REPO_ROOT / "custom_nodes" / "yoloe_open_vocab_nodes" / "manifest.json"
    catalog_path = REPO_ROOT / "custom_nodes" / "yoloe_open_vocab_nodes" / "workflow" / "catalog.json"

    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    catalog_payload = json.loads(catalog_path.read_text(encoding="utf-8"))

    manifest = NodePackManifest.model_validate(manifest_payload)
    catalog = CustomNodeCatalogDocument.model_validate(catalog_payload)

    assert manifest.node_pack_id == "yoloe.open-vocab-nodes"
    assert len(catalog.node_definitions) == 3


def test_yoloe_and_sam3_pretrained_manifest_skeletons_are_present() -> None:
    """验证 YOLOE 与 SAM3 资产说明已经挂到架构入口。"""

    docs_readme = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    architecture_readme = (REPO_ROOT / "docs" / "architecture" / "README.md").read_text(encoding="utf-8")

    assert "yoloe-sam3-node-assets.md" in docs_readme
    assert "yoloe-sam3-node-assets.md" in architecture_readme
