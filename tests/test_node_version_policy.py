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
from backend.version import BACKEND_VERSION


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_core_node_defaults_to_current_backend_version() -> None:
    """验证 core node 默认采用当前后端版本，不再隐式回填历史版本。"""

    definition = NodeDefinition(
        node_type_id="core.test.unchanged",
        display_name="Unchanged",
        category="core.test.version",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
    )

    assert definition.version == BACKEND_VERSION


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
        version="7.2.1",
        node_pack_id="test.nodes",
        node_pack_version=BACKEND_VERSION,
    )

    assert changed.version == BACKEND_VERSION
    assert unchanged.version == "7.2.1"
    assert changed.node_pack_version == unchanged.node_pack_version


@pytest.mark.parametrize("field_name", ("version", "node_pack_version"))
def test_node_definition_accepts_version_independent_from_backend(field_name: str) -> None:
    """验证节点实现版本和节点包版本拥有独立 SemVer 生命周期。"""

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
    values[field_name] = "18.4.2"

    definition = NodeDefinition.model_validate(values)

    assert getattr(definition, field_name) == "18.4.2"


def test_node_pack_manifest_accepts_version_independent_from_backend() -> None:
    """验证 manifest 版本不错误绑定到平台后端版本。"""

    manifest = NodePackManifest.model_validate(
        {
            "format_id": "amvision.node-pack-manifest.v1",
            "id": "future.nodes",
            "version": "18.4.2",
            "displayName": "Future Nodes",
            "category": "integration",
            "capabilities": ["test.version"],
            "compatibility": {"api": ">=0.1,<1.0", "runtime": ">=3.12"},
            "timeout": {"defaultSeconds": 30, "maxSeconds": 60},
            "execution": {
                "isolation": "workflow-process",
                "timeoutAction": "terminate-workflow-process",
            },
        }
    )

    assert manifest.version == "18.4.2"


def test_repository_node_versions_are_valid_and_pack_identity_matches() -> None:
    """验证仓库节点版本有效，custom node 与所属 manifest 身份严格一致。"""

    core_definitions = {
        item.node_type_id: item for item in get_core_workflow_node_definitions()
    }
    loader = LocalNodePackLoader(REPOSITORY_ROOT / "custom_nodes")
    loader.refresh()
    custom_definitions = {
        item.node_type_id: item for item in loader.get_workflow_node_definitions()
    }

    manifest_versions = {
        manifest.node_pack_id: manifest.version for manifest in loader.get_node_pack_manifests()
    }
    for definition in (*core_definitions.values(), *custom_definitions.values()):
        Version(definition.version)
        if definition.node_pack_id is not None:
            assert definition.node_pack_version == manifest_versions[definition.node_pack_id]

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

    Version(custom_definitions["custom.camera.usb.close-device"].version)
    Version(custom_definitions["custom.sam3.load-checkpoint"].version)
