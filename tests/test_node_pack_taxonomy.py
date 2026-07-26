"""统一 node pack 边界和分类规则测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.contracts.nodes.node_pack_manifest import NodePackManifest
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

    assert {
        "opencv.nodes",
        "camera.nodes",
        "database.nodes",
        "http.nodes",
    }.issubset(manifest_index)
    assert {
        "opencv.basic-nodes",
        "opencv.geometry-nodes",
        "opencv.measurement-nodes",
        "camera.usb-uvc-nodes",
        "output.local-db-nodes",
        "output.mes-http-nodes",
    }.isdisjoint(manifest_index)

    assert manifest_index["opencv.nodes"].implementation_layout == "categories"
    assert manifest_index["camera.nodes"].implementation_layout == "providers"
    assert manifest_index["database.nodes"].implementation_layout == "providers"
    assert manifest_index["http.nodes"].implementation_layout == "recipes"


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
            "opencv.nodes",
            "camera.nodes",
            "database.nodes",
            "http.nodes",
        }:
            continue
        category_root = manifest_index[definition.node_pack_id].category_root
        assert category_root is not None
        assert (
            definition.category == category_root
            or definition.category.startswith(f"{category_root}.")
        )


def test_http_pack_exposes_generic_request_and_hides_legacy_mes_node() -> None:
    """验证 HTTP 通用节点为首选，旧 MES id 只保留执行兼容。"""

    loader = LocalNodePackLoader(REPOSITORY_ROOT / "custom_nodes")
    loader.refresh()
    http_definitions = {
        definition.node_type_id: definition
        for definition in loader.get_workflow_node_definitions()
        if definition.node_pack_id == "http.nodes"
    }

    assert http_definitions["custom.http.request"].metadata.get("catalogHidden") is not True
    legacy_definition = http_definitions["custom.output.mes-http-post"]
    assert legacy_definition.metadata["catalogHidden"] is True
    assert legacy_definition.metadata["preferredNodeTypeId"] == "custom.http.request"


def test_database_pack_exposes_sql_upsert_and_hides_legacy_output_node() -> None:
    """验证 Database 使用技术域命名，旧 output id 只保留执行兼容。"""

    loader = LocalNodePackLoader(REPOSITORY_ROOT / "custom_nodes")
    loader.refresh()
    database_definitions = {
        definition.node_type_id: definition
        for definition in loader.get_workflow_node_definitions()
        if definition.node_pack_id == "database.nodes"
    }

    assert (
        database_definitions["custom.database.sql.upsert"].metadata.get(
            "catalogHidden"
        )
        is not True
    )
    legacy_definition = database_definitions["custom.output.local-db-upsert"]
    assert legacy_definition.metadata["catalogHidden"] is True
    assert (
        legacy_definition.metadata["preferredNodeTypeId"]
        == "custom.database.sql.upsert"
    )


def test_manifest_rejects_current_id_inside_migration_aliases() -> None:
    """验证迁移别名不能反向包含当前 pack id。"""

    with pytest.raises(ValidationError, match="migration_aliases"):
        NodePackManifest.model_validate(
            {
                "format_id": "amvision.node-pack-manifest.v1",
                "id": "example.nodes",
                "version": "0.1.0",
                "displayName": "Example Nodes",
                "category": "example",
                "capabilities": ["pipeline.node"],
                "migrationAliases": ["example.nodes"],
            }
        )
