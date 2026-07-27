"""PLC 统一节点目录生成器。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.nodes.node_pack_manifest import CustomNodeCatalogDocument
from backend.contracts.workflows.workflow_graph import validate_node_definition_catalog
from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from custom_nodes.plc_nodes.protocols.modbus_tcp.workflow.catalog_builder import (
    build_custom_node_catalog_payload as build_modbus_tcp_catalog_payload,
)


NODE_PACK_ID = "plc.nodes"
NODE_PACK_VERSION = "0.2.0"


def get_workflow_dir() -> Path:
    """返回 PLC 统一 workflow 目录。"""

    return Path(__file__).resolve().parent


def _read_category(node_type_id: str) -> str:
    """根据稳定节点类型返回 PLC 分类。"""

    if node_type_id.endswith("read-value"):
        return "plc.modbus_tcp.read"
    if node_type_id.endswith("wait-condition"):
        return "plc.modbus_tcp.wait"
    return "plc.modbus_tcp.write"


def build_custom_node_catalog_document() -> CustomNodeCatalogDocument:
    """合并 PLC 协议目录。"""

    payload = build_modbus_tcp_catalog_payload()
    definitions: list[dict[str, object]] = []
    for raw_definition in payload["node_definitions"]:
        definition = dict(raw_definition)
        node_type_id = str(definition["node_type_id"])
        definition["node_pack_id"] = NODE_PACK_ID
        definition["node_pack_version"] = NODE_PACK_VERSION
        definition["category"] = _read_category(node_type_id)
        definitions.append(definition)

    document = CustomNodeCatalogDocument.model_validate(
        {
            **payload,
            "node_definitions": definitions,
            "metadata": {
                "categoryRoot": "plc",
                "protocolLayout": "protocols/<protocol>",
                "protocols": ["modbus-tcp"],
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
    """生成 PLC 统一 catalog.json。"""

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
