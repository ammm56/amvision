"""核心节点、自定义节点和节点包版本策略测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from packaging.version import Version

from backend.contracts.nodes.node_pack_manifest import NodePackManifest
from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_IMPLEMENTATION_CUSTOM,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
)
from backend.nodes.core_catalog import get_core_workflow_node_definitions
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.version import BACKEND_VERSION, PREVIOUS_BACKEND_VERSION


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_core_node_defaults_to_previous_backend_version() -> None:
    """验证未修改的 core node 默认保持上一后端版本。"""

    definition = NodeDefinition(
        node_type_id="core.test.unchanged",
        display_name="Unchanged",
        category="core.test.version",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
    )

    assert definition.version == PREVIOUS_BACKEND_VERSION


def test_custom_node_version_is_independent_from_pack_version() -> None:
    """验证同一节点包可区分修改节点和未修改节点的实现版本。"""

    changed = NodeDefinition(
        node_type_id="custom.test.changed",
        display_name="Changed",
        category="test.version.changed",
        implementation_kind=NODE_IMPLEMENTATION_CUSTOM,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        version=BACKEND_VERSION,
        node_pack_id="test.nodes",
        node_pack_version=BACKEND_VERSION,
    )
    unchanged = NodeDefinition(
        node_type_id="custom.test.unchanged",
        display_name="Unchanged",
        category="test.version.unchanged",
        implementation_kind=NODE_IMPLEMENTATION_CUSTOM,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        version=PREVIOUS_BACKEND_VERSION,
        node_pack_id="test.nodes",
        node_pack_version=BACKEND_VERSION,
    )

    assert changed.version == BACKEND_VERSION
    assert unchanged.version == PREVIOUS_BACKEND_VERSION
    assert changed.node_pack_version == unchanged.node_pack_version


@pytest.mark.parametrize("field_name", ("version", "node_pack_version"))
def test_node_definition_rejects_version_above_backend(field_name: str) -> None:
    """验证单节点版本和节点包版本都不能高于后端版本。"""

    values = {
        "node_type_id": "custom.test.future",
        "display_name": "Future",
        "category": "test.version.future",
        "implementation_kind": NODE_IMPLEMENTATION_CUSTOM,
        "runtime_kind": NODE_RUNTIME_PYTHON_CALLABLE,
        "version": BACKEND_VERSION,
        "node_pack_id": "test.nodes",
        "node_pack_version": BACKEND_VERSION,
    }
    values[field_name] = "0.1.5"

    with pytest.raises(ValueError, match="不能高于后端版本"):
        NodeDefinition.model_validate(values)


def test_node_pack_manifest_rejects_version_above_backend() -> None:
    """验证 manifest 不能声明高于后端的节点包版本。"""

    with pytest.raises(ValueError, match="不能高于后端版本"):
        NodePackManifest.model_validate(
            {
                "format_id": "amvision.node-pack-manifest.v1",
                "id": "future.nodes",
                "version": "0.1.5",
                "displayName": "Future Nodes",
                "category": "integration",
                "capabilities": ["test.version"],
            }
        )


def test_repository_node_versions_follow_current_change_boundary() -> None:
    """验证仓库节点版本上限以及本次修改节点的精确版本。"""

    core_definitions = {
        item.node_type_id: item for item in get_core_workflow_node_definitions()
    }
    loader = LocalNodePackLoader(REPOSITORY_ROOT / "custom_nodes")
    loader.refresh()
    custom_definitions = {
        item.node_type_id: item for item in loader.get_workflow_node_definitions()
    }

    for definition in (*core_definitions.values(), *custom_definitions.values()):
        assert Version(definition.version) <= Version(BACKEND_VERSION)
        if definition.node_pack_version is not None:
            assert Version(definition.node_pack_version) <= Version(BACKEND_VERSION)
    for manifest in loader.get_node_pack_manifests():
        assert Version(manifest.version) <= Version(BACKEND_VERSION)

    expected_changed_nodes = {
        "core.model.classification",
        "core.model.detection",
        "core.model.obb",
        "core.model.pose",
        "core.model.sahi-inference",
        "core.model.segmentation",
        "custom.camera.usb.capture-frame",
        "custom.camera.usb.read-latest-frame",
        "custom.camera.usb.read-window",
        "custom.sam3.interactive-segment",
        "custom.sam3.semantic-segment",
        "custom.sam3.video-interactive-segment",
        "custom.sam3.video-semantic-segment",
        "custom.yoloe.prompt-free-detect",
        "custom.yoloe.text-prompt-detect",
        "custom.yoloe.visual-prompt-detect",
    }
    combined_definitions = {**core_definitions, **custom_definitions}
    assert expected_changed_nodes <= combined_definitions.keys()
    assert {
        node_type_id
        for node_type_id in expected_changed_nodes
        if combined_definitions[node_type_id].version != BACKEND_VERSION
    } == set()

    assert custom_definitions["custom.camera.usb.close-device"].version == (
        PREVIOUS_BACKEND_VERSION
    )
    assert custom_definitions["custom.sam3.load-checkpoint"].version == (
        PREVIOUS_BACKEND_VERSION
    )
