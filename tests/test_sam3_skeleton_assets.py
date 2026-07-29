"""SAM3 资产骨架和节点包骨架校验。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.nodes.node_pack_manifest import CustomNodeCatalogDocument, NodePackManifest
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)


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
        "custom.sam3.load-checkpoint",
        "custom.sam3.semantic-segment",
        "custom.sam3.video-interactive-segment",
        "custom.sam3.video-semantic-segment",
    }
    definitions = {
        node.node_type_id: node for node in catalog.node_definitions
    }
    loader = definitions["custom.sam3.load-checkpoint"]
    assert loader.output_ports[0].payload_type_id == "sam3-model-session.v1"
    for node_type_id in (
        "custom.sam3.interactive-segment",
        "custom.sam3.semantic-segment",
        "custom.sam3.video-interactive-segment",
        "custom.sam3.video-semantic-segment",
    ):
        definition = definitions[node_type_id]
        assert definition.input_ports[0].name == "model"
        assert definition.input_ports[0].payload_type_id == "sam3-model-session.v1"
        properties = definition.parameter_schema["properties"]
        assert "model_asset_id" not in properties
        assert "device" not in properties
        assert "precision" not in properties


def test_sam3_load_checkpoint_registers_model_session_provider() -> None:
    """验证 SAM3 node pack 把 loader provider 注册到通用运行时。"""

    node_pack_loader = LocalNodePackLoader(REPO_ROOT / "custom_nodes")
    node_pack_loader.refresh()
    registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=NodeCatalogRegistry(
            node_pack_loader=node_pack_loader
        ),
        node_pack_loader=node_pack_loader,
    )
    registry_loader.refresh()

    provider = registry_loader.get_runtime_registry().get_model_session_provider(
        "custom.sam3.load-checkpoint"
    )
    assert provider is not None
    assert provider.model_family == "sam3"
