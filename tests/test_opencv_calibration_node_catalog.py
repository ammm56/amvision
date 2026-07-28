"""OpenCV 标定节点目录测试。"""

from __future__ import annotations

import json
from pathlib import Path

from custom_nodes.opencv_nodes.categories.calibration.workflow.catalog_builder import (
    build_custom_node_catalog_payload,
)


def test_opencv_calibration_node_catalog_builder_matches_checked_in_catalog() -> None:
    """验证 calibration 分类目录与受控 Catalog 一致。"""

    repository_root = Path(__file__).resolve().parents[1]
    workflow_dir = (
        repository_root
        / "custom_nodes"
        / "opencv_nodes"
        / "categories"
        / "calibration"
        / "workflow"
    )
    expected = json.loads((workflow_dir / "catalog.json").read_text(encoding="utf-8"))
    actual = build_custom_node_catalog_payload(workflow_dir=workflow_dir)

    assert actual == expected
    assert {item["node_type_id"] for item in actual["node_definitions"]} == {
        "custom.opencv.chessboard-corners",
        "custom.opencv.camera-calibrate",
        "custom.opencv.solve-pnp",
        "custom.opencv.circle-grid-detect",
        "custom.opencv.corner-subpix",
        "custom.opencv.fisheye-calibrate",
        "custom.opencv.project-points",
        "custom.opencv.undistort-points",
        "custom.opencv.hand-eye-calibrate",
    }
    assert {item["node_pack_version"] for item in actual["node_definitions"]} == {"0.1.3"}
