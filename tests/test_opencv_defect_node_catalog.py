"""OpenCV 缺陷节点目录生成测试。"""

from __future__ import annotations

import json
from pathlib import Path

from custom_nodes.opencv_nodes.categories.defect.workflow.catalog_builder import (
    build_custom_node_catalog_payload,
)


def test_opencv_defect_node_catalog_builder_matches_checked_in_catalog() -> None:
    """验证 defect pack 的 catalog 碎片生成结果与仓库内 catalog.json 保持一致。"""

    repository_root = Path(__file__).resolve().parents[1]
    workflow_dir = repository_root / "custom_nodes" / "opencv_nodes" / "categories" / "defect" / "workflow"
    expected_catalog_payload = json.loads((workflow_dir / "catalog.json").read_text(encoding="utf-8"))
    actual_catalog_payload = build_custom_node_catalog_payload(workflow_dir=workflow_dir)

    assert actual_catalog_payload == expected_catalog_payload
    assert {
        item["node_type_id"] for item in actual_catalog_payload["node_definitions"]
    } == {
        "custom.opencv.image-diff",
        "custom.opencv.absdiff-threshold",
        "custom.opencv.connected-components",
        "custom.opencv.fill-holes",
        "custom.opencv.distance-transform",
        "custom.opencv.heatmap-preview",
        "custom.opencv.watershed",
        "custom.opencv.skeletonize",
        "custom.opencv.flood-fill",
        "custom.opencv.grabcut",
        "custom.opencv.kmeans-segment",
        "custom.opencv.watershed-markers",
        "custom.opencv.remove-small-components",
        "custom.opencv.clear-border",
        "custom.opencv.region-union",
        "custom.opencv.region-intersection",
        "custom.opencv.region-difference",
        "custom.opencv.morphology-hitmiss",
    }
    assert {item["node_pack_id"] for item in actual_catalog_payload["node_definitions"]} == {
        "opencv.nodes"
    }
