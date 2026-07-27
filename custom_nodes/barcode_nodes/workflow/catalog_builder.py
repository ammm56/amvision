"""Barcode 统一节点目录生成器。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.nodes.node_pack_manifest import (
    CUSTOM_NODE_CATALOG_FORMAT,
    CustomNodeCatalogDocument,
)
from backend.contracts.workflows.workflow_graph import validate_node_definition_catalog
from backend.nodes.core_catalog import get_core_workflow_payload_contracts


NODE_PACK_ID = "barcode.nodes"
NODE_PACK_VERSION = "0.2.0"


def get_workflow_dir() -> Path:
    """返回 Barcode 统一 workflow 目录。"""

    return Path(__file__).resolve().parent


def get_node_source_paths(
    *, node_pack_dir: Path | None = None
) -> tuple[Path, ...]:
    """返回所有 Barcode 分类节点定义。"""

    resolved_node_pack_dir = node_pack_dir or get_workflow_dir().parent
    categories_dir = resolved_node_pack_dir / "categories"
    return tuple(
        sorted(
            categories_dir.glob("*/workflow/nodes/*.json"),
            key=lambda path: (path.parts[-4], path.name),
        )
    )


def _load_json_document(file_path: Path) -> object:
    """读取 JSON 文档。"""

    return json.loads(file_path.read_text(encoding="utf-8"))


def build_custom_node_catalog_document(
    *, node_pack_dir: Path | None = None
) -> CustomNodeCatalogDocument:
    """构造 Barcode 统一节点目录。"""

    resolved_node_pack_dir = node_pack_dir or get_workflow_dir().parent
    payload_contracts_path = (
        resolved_node_pack_dir
        / "workflow"
        / "catalog_sources"
        / "payload_contracts.json"
    )
    payload_contracts = _load_json_document(payload_contracts_path)
    if not isinstance(payload_contracts, list):
        raise ValueError("payload_contracts.json 必须是数组")

    node_definitions: list[dict[str, object]] = []
    for node_file_path in get_node_source_paths(
        node_pack_dir=resolved_node_pack_dir
    ):
        raw_definition = _load_json_document(node_file_path)
        if not isinstance(raw_definition, dict):
            raise ValueError(f"节点目录碎片必须是对象: {node_file_path}")
        definition = dict(raw_definition)
        definition["node_pack_id"] = NODE_PACK_ID
        definition["node_pack_version"] = NODE_PACK_VERSION
        node_definitions.append(definition)

    document = CustomNodeCatalogDocument.model_validate(
        {
            "format_id": CUSTOM_NODE_CATALOG_FORMAT,
            "payload_contracts": payload_contracts,
            "node_definitions": node_definitions,
            "metadata": {
                "categoryRoot": "barcode",
                "sourceLayout": "categories/<category>",
            },
        }
    )
    validate_node_definition_catalog(
        node_definitions=document.node_definitions,
        payload_contracts=get_core_workflow_payload_contracts()
        + document.payload_contracts,
    )
    return document


def build_custom_node_catalog_payload(
    *, node_pack_dir: Path | None = None
) -> dict[str, object]:
    """返回可写入 JSON 的 Barcode 节点目录。"""

    return build_custom_node_catalog_document(
        node_pack_dir=node_pack_dir
    ).model_dump(mode="json")


def write_custom_node_catalog() -> Path:
    """生成 Barcode 统一 catalog.json。"""

    catalog_path = get_workflow_dir() / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            build_custom_node_catalog_payload(),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return catalog_path
