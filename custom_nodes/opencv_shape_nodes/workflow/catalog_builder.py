"""OpenCV 形状节点目录生成器。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.nodes.node_pack_manifest import (
    CUSTOM_NODE_CATALOG_FORMAT,
    CustomNodeCatalogDocument,
)
from backend.contracts.workflows.workflow_graph import validate_node_definition_catalog
from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from custom_nodes._opencv_shared.workflow.payload_contracts import (
    load_shared_opencv_payload_contracts_payload,
)


def get_workflow_dir() -> Path:
    """返回 OpenCV 形状节点 workflow 目录。"""

    return Path(__file__).resolve().parent


def get_catalog_sources_dir(*, workflow_dir: Path | None = None) -> Path:
    """返回 catalog_sources 目录。"""

    resolved_workflow_dir = workflow_dir or get_workflow_dir()
    return resolved_workflow_dir / "catalog_sources"


def get_node_sources_dir(*, workflow_dir: Path | None = None) -> Path:
    """返回节点定义 JSON 目录。"""

    return get_catalog_sources_dir(workflow_dir=workflow_dir) / "nodes"


def _load_json_document(file_path: Path) -> object:
    """读取单个 JSON 文档。"""

    return json.loads(file_path.read_text(encoding="utf-8"))


def build_custom_node_catalog_document(*, workflow_dir: Path | None = None) -> CustomNodeCatalogDocument:
    """从 workflow/catalog_sources 构造完整目录文档。"""

    resolved_workflow_dir = workflow_dir or get_workflow_dir()
    node_definitions_payload: list[dict[str, object]] = []
    for node_file_path in sorted(get_node_sources_dir(workflow_dir=resolved_workflow_dir).glob("*.json")):
        node_payload = _load_json_document(node_file_path)
        if not isinstance(node_payload, dict):
            raise ValueError(f"节点目录碎片必须是对象: {node_file_path.name}")
        node_definitions_payload.append(node_payload)

    catalog_document = CustomNodeCatalogDocument.model_validate(
        {
            "format_id": CUSTOM_NODE_CATALOG_FORMAT,
            "payload_contracts": load_shared_opencv_payload_contracts_payload(),
            "node_definitions": node_definitions_payload,
        }
    )
    validate_node_definition_catalog(
        node_definitions=catalog_document.node_definitions,
        payload_contracts=get_core_workflow_payload_contracts() + catalog_document.payload_contracts,
    )
    return catalog_document


def build_custom_node_catalog_payload(*, workflow_dir: Path | None = None) -> dict[str, object]:
    """构造可直接写入 catalog.json 的 JSON payload。"""

    return build_custom_node_catalog_document(workflow_dir=workflow_dir).model_dump(mode="json")


def write_custom_node_catalog(*, workflow_dir: Path | None = None) -> Path:
    """把 workflow/catalog_sources 汇总写回 catalog.json。"""

    resolved_workflow_dir = workflow_dir or get_workflow_dir()
    catalog_path = resolved_workflow_dir / "catalog.json"
    catalog_payload = build_custom_node_catalog_payload(workflow_dir=resolved_workflow_dir)
    catalog_path.write_text(
        json.dumps(catalog_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return catalog_path

