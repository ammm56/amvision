"""OpenCV 量测节点目录生成测试。"""

from __future__ import annotations

import json
from pathlib import Path

from custom_nodes.opencv_measurement_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_payload,
)


def test_opencv_measurement_node_catalog_builder_matches_checked_in_catalog() -> None:
    """验证 measurement pack 的 catalog 碎片生成结果与仓库内 catalog.json 保持一致。"""

    repository_root = Path(__file__).resolve().parents[1]
    workflow_dir = repository_root / "custom_nodes" / "opencv_measurement_nodes" / "workflow"
    expected_catalog_payload = json.loads((workflow_dir / "catalog.json").read_text(encoding="utf-8"))
    actual_catalog_payload = build_custom_node_catalog_payload(workflow_dir=workflow_dir)

    assert actual_catalog_payload == expected_catalog_payload
    assert {
        item["node_type_id"] for item in actual_catalog_payload["node_definitions"]
    } == {
        "custom.opencv.measure",
        "custom.opencv.caliper-edge",
        "custom.opencv.point-distance",
        "custom.opencv.point-to-line-distance",
        "custom.opencv.line-angle",
        "custom.opencv.circle-diameter",
        "custom.opencv.slot-width",
        "custom.opencv.parallelism-metrics",
        "custom.opencv.concentricity-metrics",
    }
    assert {item["node_pack_id"] for item in actual_catalog_payload["node_definitions"]} == {
        "opencv.measurement-nodes"
    }
    node_by_type = {
        item["node_type_id"]: item
        for item in actual_catalog_payload["node_definitions"]
    }
    caliper_properties = node_by_type["custom.opencv.caliper-edge"]["parameter_schema"]["properties"]
    assert caliper_properties["max_results"]["default"] == 10
    assert caliper_properties["max_results"]["maximum"] == 1000
    assert "line_xyxy" in caliper_properties
    assert "min_edge_distance" in caliper_properties

