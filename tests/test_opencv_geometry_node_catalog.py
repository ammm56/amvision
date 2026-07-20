"""OpenCV 几何节点目录生成测试。"""

from __future__ import annotations

import json
from pathlib import Path

from custom_nodes.opencv_geometry_nodes.workflow.catalog_builder import build_custom_node_catalog_payload


def test_opencv_geometry_node_catalog_builder_matches_checked_in_catalog() -> None:
    """验证 geometry pack 的 catalog 碎片生成结果与仓库内 catalog.json 保持一致。"""

    repository_root = Path(__file__).resolve().parents[1]
    workflow_dir = repository_root / "custom_nodes" / "opencv_geometry_nodes" / "workflow"
    expected_catalog_payload = json.loads((workflow_dir / "catalog.json").read_text(encoding="utf-8"))
    actual_catalog_payload = build_custom_node_catalog_payload(workflow_dir=workflow_dir)

    assert actual_catalog_payload == expected_catalog_payload
    assert {item["payload_type_id"] for item in actual_catalog_payload["payload_contracts"]} >= {
        "local-features.v1",
        "feature-matches.v1",
        "planar-transform.v1",
    }
    assert {item["node_type_id"] for item in actual_catalog_payload["node_definitions"]} == {
        "custom.opencv.rotation-correct",
        "custom.opencv.perspective-transform",
        "custom.opencv.affine-transform",
        "custom.opencv.planar-transform-bridge",
        "custom.opencv.undistort",
        "custom.opencv.remap",
        "custom.opencv.quadrilateral-from-circle-centers",
        "custom.opencv.line-deduplicate",
        "custom.opencv.line-intersection",
        "custom.opencv.quadrilateral-from-lines",
    }
    assert {item["node_pack_id"] for item in actual_catalog_payload["node_definitions"]} == {
        "opencv.geometry-nodes"
    }
    node_by_type = {
        item["node_type_id"]: item
        for item in actual_catalog_payload["node_definitions"]
    }
    quadrilateral_node = node_by_type[
        "custom.opencv.quadrilateral-from-circle-centers"
    ]
    assert [port["name"] for port in quadrilateral_node["input_ports"]] == [
        "top_left",
        "top_right",
        "bottom_right",
        "bottom_left",
    ]
    assert all(
        port.get("description")
        for port in quadrilateral_node["input_ports"]
    )
