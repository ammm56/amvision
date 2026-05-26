"""Barcode/QR 协议节点目录生成器。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.nodes.node_pack_manifest import CUSTOM_NODE_CATALOG_FORMAT, CustomNodeCatalogDocument
from backend.contracts.workflows.workflow_graph import validate_node_definition_catalog
from backend.nodes.core_catalog import get_core_workflow_payload_contracts


def get_workflow_dir() -> Path:
    """返回 Barcode/QR 节点包 workflow 目录。

    返回：
    - Path：workflow 目录绝对路径。
    """

    return Path(__file__).resolve().parent


def get_catalog_sources_dir(*, workflow_dir: Path | None = None) -> Path:
    """返回 catalog_sources 目录。

    参数：
    - workflow_dir：可选 workflow 目录；未提供时使用当前模块目录。

    返回：
    - Path：catalog_sources 目录绝对路径。
    """

    resolved_workflow_dir = workflow_dir or get_workflow_dir()
    return resolved_workflow_dir / "catalog_sources"


def get_node_sources_dir(*, workflow_dir: Path | None = None) -> Path:
    """返回节点定义 JSON 目录。

    参数：
    - workflow_dir：可选 workflow 目录；未提供时使用当前模块目录。

    返回：
    - Path：workflow/catalog_sources/nodes 目录绝对路径。
    """

    return get_catalog_sources_dir(workflow_dir=workflow_dir) / "nodes"


def _load_json_document(file_path: Path) -> object:
    """读取单个 JSON 文档。

    参数：
    - file_path：JSON 文件路径。

    返回：
    - object：解析后的 JSON 结构。
    """

    return json.loads(file_path.read_text(encoding="utf-8"))


def _load_node_definitions_payload(*, node_sources_dir: Path) -> list[dict[str, object]]:
    """读取节点定义 JSON 碎片。

    参数：
    - node_sources_dir：workflow/catalog_sources/nodes 目录。

    返回：
    - list[dict[str, object]]：按文件名排序后的节点定义 payload 列表。
    """

    node_definitions_payload: list[dict[str, object]] = []
    for node_file_path in sorted(node_sources_dir.glob("*.json")):
        node_payload = _load_json_document(node_file_path)
        if not isinstance(node_payload, dict):
            raise ValueError(f"节点目录碎片必须是对象: {node_file_path.name}")
        node_definitions_payload.append(node_payload)
    return node_definitions_payload


def build_custom_node_catalog_document(*, workflow_dir: Path | None = None) -> CustomNodeCatalogDocument:
    """从 workflow/catalog_sources 构造完整目录文档。

    参数：
    - workflow_dir：可选 workflow 目录；未提供时使用当前模块目录。

    返回：
    - CustomNodeCatalogDocument：校验通过的自定义节点目录文档。
    """

    catalog_sources_dir = get_catalog_sources_dir(workflow_dir=workflow_dir)
    node_sources_dir = get_node_sources_dir(workflow_dir=workflow_dir)
    payload_contracts_path = catalog_sources_dir / "payload_contracts.json"
    metadata_path = catalog_sources_dir / "metadata.json"
    payload_contracts_payload = _load_json_document(payload_contracts_path)
    if not isinstance(payload_contracts_payload, list):
        raise ValueError("payload_contracts.json 必须是数组")
    metadata_payload: dict[str, object] = {}
    if metadata_path.is_file():
        raw_metadata_payload = _load_json_document(metadata_path)
        if not isinstance(raw_metadata_payload, dict):
            raise ValueError("metadata.json 必须是对象")
        metadata_payload = raw_metadata_payload

    node_definitions_payload = _load_node_definitions_payload(node_sources_dir=node_sources_dir)

    catalog_document = CustomNodeCatalogDocument.model_validate(
        {
            "format_id": CUSTOM_NODE_CATALOG_FORMAT,
            "payload_contracts": payload_contracts_payload,
            "node_definitions": node_definitions_payload,
            "metadata": metadata_payload,
        }
    )
    validation_payload_contracts = get_core_workflow_payload_contracts() + catalog_document.payload_contracts
    validate_node_definition_catalog(
        node_definitions=catalog_document.node_definitions,
        payload_contracts=validation_payload_contracts,
    )
    return catalog_document


def build_custom_node_catalog_payload(*, workflow_dir: Path | None = None) -> dict[str, object]:
    """构造可直接写入 catalog.json 的 JSON payload。

    参数：
    - workflow_dir：可选 workflow 目录；未提供时使用当前模块目录。

    返回：
    - dict[str, object]：可序列化的 catalog JSON 结构。
    """

    catalog_document = build_custom_node_catalog_document(workflow_dir=workflow_dir)
    return catalog_document.model_dump(mode="json")


def write_custom_node_catalog(*, workflow_dir: Path | None = None) -> Path:
    """把 workflow/catalog_sources 汇总写回 catalog.json。

    参数：
    - workflow_dir：可选 workflow 目录；未提供时使用当前模块目录。

    返回：
    - Path：写入完成的 catalog.json 路径。
    """

    resolved_workflow_dir = workflow_dir or get_workflow_dir()
    catalog_path = resolved_workflow_dir / "catalog.json"
    catalog_payload = build_custom_node_catalog_payload(workflow_dir=resolved_workflow_dir)
    catalog_path.write_text(
        json.dumps(catalog_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return catalog_path
