"""Camera 统一节点目录生成器。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.nodes.node_pack_manifest import CustomNodeCatalogDocument
from backend.contracts.workflows.workflow_graph import validate_node_definition_catalog
from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from custom_nodes.camera_nodes.providers.usb_uvc.workflow.catalog_builder import (
    build_custom_node_catalog_payload as build_usb_uvc_catalog_payload,
)


NODE_PACK_ID = "camera.nodes"
NODE_PACK_VERSION = "0.2.0"


def get_workflow_dir() -> Path:
    """返回 Camera 统一 workflow 目录。"""

    return Path(__file__).resolve().parent


def build_custom_node_catalog_document() -> CustomNodeCatalogDocument:
    """合并当前 Camera provider 的节点定义。"""

    payload = build_usb_uvc_catalog_payload()
    definitions = []
    for raw_definition in payload["node_definitions"]:
        definition = dict(raw_definition)
        definition["node_pack_id"] = NODE_PACK_ID
        definition["node_pack_version"] = NODE_PACK_VERSION
        definitions.append(definition)
    document = CustomNodeCatalogDocument.model_validate(
        {
            **payload,
            "node_definitions": definitions,
            "metadata": {
                "categoryRoot": "camera",
                "providerLayout": "providers/<provider>",
                "providers": ["usb-uvc"],
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
    """生成 Camera 统一目录文件。"""

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
