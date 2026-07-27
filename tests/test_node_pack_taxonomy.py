"""统一 node pack 边界和分类规则测试。"""

from __future__ import annotations

from pathlib import Path

from backend.nodes.local_node_pack_loader import LocalNodePackLoader


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_common_node_packs_use_one_manifest_per_technical_domain() -> None:
    """验证通用技术域不再按功能小类或业务场景拆成一级 pack。"""

    loader = LocalNodePackLoader(REPOSITORY_ROOT / "custom_nodes")
    loader.refresh()
    manifest_index = {
        manifest.node_pack_id: manifest
        for manifest in loader.get_node_pack_manifests()
    }

    assert set(manifest_index) == {
        "barcode.nodes",
        "camera.nodes",
        "database.nodes",
        "hello.world-nodes",
        "http.nodes",
        "opencv.nodes",
        "plc.nodes",
        "sam3.segment-nodes",
        "yoloe.open-vocab-nodes",
    }

    assert manifest_index["barcode.nodes"].implementation_layout == "categories"
    assert manifest_index["opencv.nodes"].implementation_layout == "categories"
    assert manifest_index["camera.nodes"].implementation_layout == "providers"
    assert manifest_index["database.nodes"].implementation_layout == "providers"
    assert manifest_index["http.nodes"].implementation_layout == "categories"
    assert manifest_index["plc.nodes"].implementation_layout == "protocols"


def test_unified_node_pack_categories_stay_below_manifest_category_root() -> None:
    """验证统一 pack 的节点分类都位于声明的根路径下。"""

    loader = LocalNodePackLoader(REPOSITORY_ROOT / "custom_nodes")
    loader.refresh()
    manifest_index = {
        manifest.node_pack_id: manifest
        for manifest in loader.get_node_pack_manifests()
    }

    for definition in loader.get_workflow_node_definitions():
        if definition.node_pack_id not in {
            "barcode.nodes",
            "opencv.nodes",
            "camera.nodes",
            "database.nodes",
            "http.nodes",
            "plc.nodes",
        }:
            continue
        category_root = manifest_index[definition.node_pack_id].category_root
        assert category_root is not None
        assert (
            definition.category == category_root
            or definition.category.startswith(f"{category_root}.")
        )


def test_http_pack_only_exposes_current_request_node() -> None:
    """验证 HTTP 目录只包含当前通用请求节点。"""

    loader = LocalNodePackLoader(REPOSITORY_ROOT / "custom_nodes")
    loader.refresh()
    http_definitions = {
        definition.node_type_id: definition
        for definition in loader.get_workflow_node_definitions()
        if definition.node_pack_id == "http.nodes"
    }

    assert set(http_definitions) == {"custom.http.request"}
    assert http_definitions["custom.http.request"].metadata.get("catalogHidden") is not True


def test_database_pack_only_exposes_current_sql_upsert_node() -> None:
    """验证 Database 目录只包含当前 SQL upsert 节点。"""

    loader = LocalNodePackLoader(REPOSITORY_ROOT / "custom_nodes")
    loader.refresh()
    database_definitions = {
        definition.node_type_id: definition
        for definition in loader.get_workflow_node_definitions()
        if definition.node_pack_id == "database.nodes"
    }

    assert set(database_definitions) == {"custom.database.sql.upsert"}
    assert (
        database_definitions["custom.database.sql.upsert"].metadata.get(
            "catalogHidden"
        )
        is not True
    )
