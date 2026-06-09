"""USB / UVC 相机节点目录测试。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from custom_nodes.camera_usb_uvc_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_payload,
)


def test_usb_uvc_node_catalog_builder_matches_checked_in_catalog() -> None:
    """验证 catalog_builder 生成结果与 checked-in catalog.json 一致。"""

    workflow_dir = (
        Path(__file__).resolve().parents[1]
        / "custom_nodes"
        / "camera_usb_uvc_nodes"
        / "workflow"
    )
    checked_in_payload = json.loads((workflow_dir / "catalog.json").read_text(encoding="utf-8"))

    assert build_custom_node_catalog_payload(workflow_dir=workflow_dir) == checked_in_payload


def test_repository_usb_uvc_node_pack_is_enabled_by_default() -> None:
    """验证仓库内置 camera.usb-uvc-nodes 会被默认加载。"""

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()

    node_pack_ids = {manifest.node_pack_id for manifest in node_pack_loader.get_node_pack_manifests()}
    loaded_node_type_ids = {node.node_type_id for node in node_pack_loader.get_workflow_node_definitions()}

    assert "camera.usb-uvc-nodes" in node_pack_ids
    assert {
        "custom.camera.usb.enumerate-devices",
        "custom.camera.usb.capture-frame",
        "custom.camera.usb.open-device",
        "custom.camera.usb.read-latest-frame",
        "custom.camera.usb.get-parameter",
        "custom.camera.usb.set-parameter",
        "custom.camera.usb.close-device",
    }.issubset(loaded_node_type_ids)
