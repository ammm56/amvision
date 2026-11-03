"""正式节点包准入；不拼接 Catalog、不替换 handler、不生成测试 manifest。"""

from pathlib import Path

from backend.contracts.nodes.node_pack_manifest import CustomNodeCatalogDocument
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from custom_nodes.metrology3d_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_document,
)


ROOT = Path(__file__).resolve().parents[3]


def test_catalog_is_generated_from_current_contracts_and_loads():
    """正式目录与生成器逐字段一致，十八个 handler 沿正常 loader 可注册。"""
    file = ROOT / "custom_nodes/metrology3d_nodes/workflow/catalog.json"
    assert (
        CustomNodeCatalogDocument.model_validate_json(file.read_text("utf-8"))
        == build_custom_node_catalog_document()
    )
    packs = LocalNodePackLoader(ROOT / "custom_nodes")
    packs.refresh()
    catalog = NodeCatalogRegistry(node_pack_loader=packs)
    definitions = [
        d
        for d in catalog.get_catalog_snapshot().node_definitions
        if d.node_pack_id == "metrology3d.nodes"
    ]
    assert len(definitions) == 18
    loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=catalog, node_pack_loader=packs
    )
    loader.refresh()
    assert loader.get_runtime_registry() is not None


def test_missing_dependency_stays_visible_but_not_executable(monkeypatch):
    """缺失几何库报告具体依赖，不从管理列表消失、不生成可执行 Catalog。"""
    from backend.contracts.nodes import node_pack_manifest as module

    original = module.distribution_version

    def version(name):
        if name == "open3d":
            raise module.PackageNotFoundError(name)
        return original(name)

    monkeypatch.setattr(module, "distribution_version", version)
    packs = LocalNodePackLoader(ROOT / "custom_nodes")
    packs.refresh()
    assert any(
        m.node_pack_id == "metrology3d.nodes" for m in packs.get_node_pack_manifests()
    )
    assert not any(
        d.node_pack_id == "metrology3d.nodes"
        for d in packs.get_catalog_snapshot().node_definitions
    )
    manifest = next(
        m
        for m in packs.get_node_pack_manifests()
        if m.node_pack_id == "metrology3d.nodes"
    )
    assert manifest.compatibility.current_incompatibilities() == (
        {
            "field": "pythonDistributions",
            "distribution": "open3d",
            "required": "==0.20.0",
            "actual": None,
        },
    )


def test_unconnected_draft_saves_but_cannot_be_published(tmp_path):
    """真实 API 拒绝必填口缺线，不写入发布版本，草稿仍可继续编辑。"""
    from tests.integration.metrology3d.published_support import published_system
    from tests.metrology3d_transport_support import cloud_documents

    template, app = cloud_documents()
    template = template.model_copy(update={"edges": ()})
    with published_system(tmp_path) as system:
        path = f"/projects/project-1/applications/{app.application_id}"
        system.call(
            "PUT",
            path,
            status=201,
            json={
                "template": template.model_dump(mode="json"),
                "application": app.model_dump(mode="json"),
            },
        )
        draft = system.call("GET", path)
        error = system.call(
            "POST",
            path + "/versions",
            status=400,
            json={
                "expected_draft_fingerprint": draft["draft_fingerprint"],
                "release_notes": "missing cloud input",
            },
        )
        assert "preview.cloud" in str(error)
        assert (
            system.call("GET", path)["draft_fingerprint"] == draft["draft_fingerprint"]
        )
