"""SAM3 资产骨架和节点包骨架校验。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.nodes.node_pack_manifest import CustomNodeCatalogDocument, NodePackManifest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_sam3_node_pack_manifest_and_catalog_are_valid() -> None:
    """验证 SAM3 节点包 manifest 与 catalog 可以按当前协议解析。"""

    manifest_path = REPO_ROOT / "custom_nodes" / "sam3_segment_nodes" / "manifest.json"
    catalog_path = REPO_ROOT / "custom_nodes" / "sam3_segment_nodes" / "workflow" / "catalog.json"

    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    catalog_payload = json.loads(catalog_path.read_text(encoding="utf-8"))

    manifest = NodePackManifest.model_validate(manifest_payload)
    catalog = CustomNodeCatalogDocument.model_validate(catalog_payload)

    assert manifest.node_pack_id == "sam3.segment-nodes"
    assert {node.node_type_id for node in catalog.node_definitions} == {
        "custom.sam3.interactive-segment",
        "custom.sam3.semantic-segment",
        "custom.sam3.video-interactive-segment",
        "custom.sam3.video-semantic-segment",
    }
