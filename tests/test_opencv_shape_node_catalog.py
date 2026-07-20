"""OpenCV 形状节点目录生成测试。"""

from __future__ import annotations

import json
from pathlib import Path

from custom_nodes.opencv_shape_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_payload,
)


def test_opencv_shape_node_catalog_builder_matches_checked_in_catalog() -> None:
    """验证 shape pack 的 catalog 碎片生成结果与仓库内 catalog.json 保持一致。"""

    repository_root = Path(__file__).resolve().parents[1]
    workflow_dir = repository_root / "custom_nodes" / "opencv_shape_nodes" / "workflow"
    expected_catalog_payload = json.loads((workflow_dir / "catalog.json").read_text(encoding="utf-8"))
    actual_catalog_payload = build_custom_node_catalog_payload(workflow_dir=workflow_dir)

    assert actual_catalog_payload == expected_catalog_payload
    assert {
        item["node_type_id"] for item in actual_catalog_payload["node_definitions"]
    } == {
        "custom.opencv.circle-measure",
        "custom.opencv.contour",
        "custom.opencv.contour-filter",
        "custom.opencv.contour-approx",
        "custom.opencv.convex-hull",
        "custom.opencv.min-area-rect",
        "custom.opencv.fit-ellipse",
        "custom.opencv.contours-to-regions",
        "custom.opencv.hough-lines",
        "custom.opencv.hough-circles",
        "custom.opencv.fit-line",
        "custom.opencv.min-enclosing-circle",
    }
    assert {item["node_pack_id"] for item in actual_catalog_payload["node_definitions"]} == {
        "opencv.shape-nodes"
    }
    assert {item["category"] for item in actual_catalog_payload["node_definitions"]} == {
        "opencv.shape"
    }
    node_by_type = {
        item["node_type_id"]: item
        for item in actual_catalog_payload["node_definitions"]
    }
    assert (
        node_by_type["custom.opencv.hough-lines"]["parameter_schema"]["properties"]["debug_image_panel_enabled"][
            "default"
        ]
        is False
    )
    assert (
        node_by_type["custom.opencv.hough-circles"]["parameter_schema"]["properties"]["debug_image_panel_enabled"][
            "default"
        ]
        is False
    )
    for node_type_id in {
        "custom.opencv.contour",
        "custom.opencv.contour-filter",
        "custom.opencv.contour-approx",
        "custom.opencv.convex-hull",
        "custom.opencv.min-area-rect",
        "custom.opencv.fit-ellipse",
        "custom.opencv.hough-lines",
        "custom.opencv.hough-circles",
        "custom.opencv.fit-line",
        "custom.opencv.min-enclosing-circle",
    }:
        properties = node_by_type[node_type_id]["parameter_schema"]["properties"]
        limit_name = (
            "max_contours"
            if node_type_id == "custom.opencv.contour"
            else "max_results"
            if node_type_id == "custom.opencv.hough-circles"
            else "limit"
        )
        assert properties[limit_name]["default"] == 10
        assert properties[limit_name]["maximum"] == 1000
    hough_line_properties = node_by_type["custom.opencv.hough-lines"]["parameter_schema"]["properties"]
    assert hough_line_properties["deduplicate"]["default"] is True
    assert hough_line_properties["processing_max_long_edge"]["default"] == 2048
    assert (
        node_by_type["custom.opencv.hough-circles"]["parameter_schema"]["properties"][
            "processing_max_long_edge_px"
        ]["default"]
        == 2048
    )
    hough_circle_properties = node_by_type["custom.opencv.hough-circles"]["parameter_schema"]["properties"]
    assert "param1" not in hough_circle_properties
    assert "param2" not in hough_circle_properties
    assert hough_circle_properties["canny_high_threshold"]["default"] == 100
    assert hough_circle_properties["center_vote_threshold"]["default"] == 20
    assert hough_circle_properties["ransac_iterations"]["default"] == 32
    assert "reference_center_xy" not in hough_circle_properties
    assert "center_tolerance_px" not in hough_circle_properties
    assert hough_circle_properties["gradient_threshold"]["default"] == 12
    assert hough_circle_properties["minimum_arc_coverage"]["default"] == 0.55
    assert hough_circle_properties["minimum_edge_support_ratio"]["default"] == 0.5
    assert hough_circle_properties["illumination_normalization"]["default"] == "clahe"
    assert hough_circle_properties["show_rejected_candidates"]["default"] is False
    assert hough_circle_properties["max_results"]["default"] == 10
    assert hough_circle_properties["maximum_candidates"]["default"] == 40
    circle_measure_node = node_by_type["custom.opencv.circle-measure"]
    circle_measure_schema = circle_measure_node["parameter_schema"]
    assert "required" not in circle_measure_schema
    assert [port["name"] for port in circle_measure_node["input_ports"]] == [
        "image",
        "roi",
        "reference_circles",
    ]
    assert circle_measure_schema["properties"]["ransac_iterations"]["default"] == 64
