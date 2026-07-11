"""OpenCV 匹配节点目录生成测试。"""

from __future__ import annotations

import json
from pathlib import Path

from custom_nodes.opencv_matching_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_payload,
)


def test_opencv_matching_node_catalog_builder_matches_checked_in_catalog() -> None:
    """验证 matching pack 的 catalog 碎片生成结果与仓库内 catalog.json 保持一致。"""

    repository_root = Path(__file__).resolve().parents[1]
    workflow_dir = repository_root / "custom_nodes" / "opencv_matching_nodes" / "workflow"
    expected_catalog_payload = json.loads((workflow_dir / "catalog.json").read_text(encoding="utf-8"))
    actual_catalog_payload = build_custom_node_catalog_payload(workflow_dir=workflow_dir)

    assert actual_catalog_payload == expected_catalog_payload
    assert {
        item["node_type_id"] for item in actual_catalog_payload["node_definitions"]
    } == {
        "custom.opencv.template-match",
        "custom.opencv.orb-keypoints",
        "custom.opencv.orb-match",
        "custom.opencv.homography-estimate",
    }
    assert {item["node_pack_id"] for item in actual_catalog_payload["node_definitions"]} == {
        "opencv.matching-nodes"
    }
    assert {item["category"] for item in actual_catalog_payload["node_definitions"]} == {
        "opencv.matching"
    }
    node_by_type = {
        item["node_type_id"]: item
        for item in actual_catalog_payload["node_definitions"]
    }
    orb_properties = node_by_type["custom.opencv.orb-keypoints"]["parameter_schema"]["properties"]
    assert "search_bbox_xyxy" in orb_properties
    assert orb_properties["debug_image_panel_enabled"]["default"] is False
    assert {
        contract["payload_type_id"] for contract in actual_catalog_payload["payload_contracts"]
    } >= {
        "local-features.v1",
        "feature-matches.v1",
        "planar-transform.v1",
    }

