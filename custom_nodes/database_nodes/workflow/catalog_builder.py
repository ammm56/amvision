"""Database 统一节点目录生成器。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.nodes.node_pack_manifest import CustomNodeCatalogDocument
from backend.contracts.workflows.workflow_graph import validate_node_definition_catalog
from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from custom_nodes.database_nodes.providers.sql.workflow.catalog_builder import (
    build_custom_node_catalog_payload as build_sql_catalog_payload,
)


NODE_PACK_ID = "database.nodes"
NODE_PACK_VERSION = "0.2.0"


def get_workflow_dir() -> Path:
    """返回 Database 统一 workflow 目录。"""

    return Path(__file__).resolve().parent


def build_custom_node_catalog_document() -> CustomNodeCatalogDocument:
    """合并 Database provider 节点定义。"""

    payload = build_sql_catalog_payload()
    definitions = []
    for raw_definition in payload["node_definitions"]:
        preferred_definition = dict(raw_definition)
        preferred_definition["node_type_id"] = "custom.database.sql.upsert"
        preferred_definition["display_name"] = "SQL Upsert"
        preferred_definition["description"] = (
            "通过受限列映射向 SQLite、MySQL 或 PostgreSQL 单表执行 upsert。"
        )
        preferred_definition["node_pack_id"] = NODE_PACK_ID
        preferred_definition["node_pack_version"] = NODE_PACK_VERSION
        preferred_definition["category"] = "database.sql.write"
        preferred_metadata = dict(preferred_definition.get("metadata") or {})
        preferred_metadata["legacyNodeTypeIds"] = [
            "custom.output.local-db-upsert"
        ]
        preferred_definition["metadata"] = preferred_metadata
        definitions.append(preferred_definition)

        legacy_definition = dict(raw_definition)
        legacy_definition["display_name"] = "Local DB Upsert (Compatibility)"
        legacy_definition["node_pack_id"] = NODE_PACK_ID
        legacy_definition["node_pack_version"] = NODE_PACK_VERSION
        legacy_definition["category"] = "database.compatibility"
        legacy_metadata = dict(legacy_definition.get("metadata") or {})
        legacy_metadata["catalogHidden"] = True
        legacy_metadata["deprecated"] = True
        legacy_metadata["preferredNodeTypeId"] = "custom.database.sql.upsert"
        legacy_definition["metadata"] = legacy_metadata
        definitions.append(legacy_definition)
    document = CustomNodeCatalogDocument.model_validate(
        {
            **payload,
            "node_definitions": definitions,
            "metadata": {
                "categoryRoot": "database",
                "providerLayout": "providers/<provider>",
                "providers": ["sql"],
                "sqlDialects": ["sqlite", "mysql", "postgresql"],
            },
        }
    )
    validate_node_definition_catalog(
        node_definitions=document.node_definitions,
        payload_contracts=get_core_workflow_payload_contracts()
        + document.payload_contracts,
    )
    return document


def write_custom_node_catalog() -> Path:
    """生成 Database 统一目录文件。"""

    catalog_path = get_workflow_dir() / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            build_custom_node_catalog_document().model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return catalog_path
