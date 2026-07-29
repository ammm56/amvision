"""OpenCV 统一节点目录生成器。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.nodes.node_pack_manifest import (
    CUSTOM_NODE_CATALOG_FORMAT,
    CustomNodeCatalogDocument,
)
from backend.contracts.workflows.workflow_graph import validate_node_definition_catalog
from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from custom_nodes.opencv_nodes.shared.workflow.payload_contracts import (
    load_shared_opencv_payload_contracts_payload,
    merge_payload_contracts_for_validation,
)


NODE_PACK_ID = "opencv.nodes"
NODE_PACK_VERSION = "0.1.3"


def get_workflow_dir() -> Path:
    """返回 OpenCV 统一 workflow 目录。"""

    return Path(__file__).resolve().parent


def get_node_source_paths() -> tuple[Path, ...]:
    """返回所有 OpenCV 分类中的节点定义文件。"""

    categories_dir = get_workflow_dir().parent / "categories"
    return tuple(
        sorted(
            categories_dir.glob("*/workflow/catalog_sources/nodes/*.json"),
            key=lambda path: (path.parts[-5], path.name),
        )
    )


def _load_json_document(file_path: Path) -> object:
    """读取单个 JSON 文档。"""

    return json.loads(file_path.read_text(encoding="utf-8"))


def build_custom_node_catalog_document() -> CustomNodeCatalogDocument:
    """合并包内分类目录并构造 OpenCV 节点目录。"""

    node_definitions: list[dict[str, object]] = []
    for node_file_path in get_node_source_paths():
        raw_node_definition = _load_json_document(node_file_path)
        if not isinstance(raw_node_definition, dict):
            raise ValueError(f"节点目录碎片必须是对象: {node_file_path}")
        node_definition = dict(raw_node_definition)
        node_definition["node_pack_id"] = NODE_PACK_ID
        node_definition["node_pack_version"] = NODE_PACK_VERSION
        node_definitions.append(node_definition)

    catalog_document = CustomNodeCatalogDocument.model_validate(
        {
            "format_id": CUSTOM_NODE_CATALOG_FORMAT,
            "payload_contracts": load_shared_opencv_payload_contracts_payload(),
            "node_definitions": node_definitions,
            "metadata": {
                "categoryRoot": "opencv",
                "categoryModel": "two-level",
                "categoryDepth": 2,
                "sourceLayout": "categories/<implementation-module>",
            },
        }
    )
    validate_node_definition_catalog(
        node_definitions=catalog_document.node_definitions,
        payload_contracts=merge_payload_contracts_for_validation(
            core_payload_contracts=get_core_workflow_payload_contracts(),
            custom_payload_contracts=catalog_document.payload_contracts,
        ),
    )
    return catalog_document


def write_custom_node_catalog() -> Path:
    """生成统一的 workflow/catalog.json。"""

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
