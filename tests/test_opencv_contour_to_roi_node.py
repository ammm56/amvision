"""OpenCV contour-to-roi 通用节点测试。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_shape_nodes.backend.nodes.contour_to_roi import handle_node
from custom_nodes.opencv_shape_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_payload,
)


def _build_contours_payload() -> dict[str, object]:
    """构造一个可用于透视变换的四点 contour payload。"""

    return {
        "items": [
            {
                "contour_index": 7,
                "point_count": 4,
                "bbox_xyxy": [10, 20, 110, 80],
                "points": [[10, 20], [110, 20], [110, 80], [10, 80]],
            }
        ],
        "count": 1,
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "tray-image",
            "media_type": "image/bgr24",
            "width": 160,
            "height": 120,
        },
    }


def test_contour_to_roi_outputs_polygon_roi_for_quad_contour() -> None:
    """验证四点 contour 可以转换为 polygon roi.v1。"""

    output = handle_node(
        WorkflowNodeExecutionRequest(
            node_id="contour-to-roi",
            node_definition=object(),
            parameters={"roi_id_prefix": "tray", "display_name_prefix": "Tray"},
            input_values={"contours": _build_contours_payload()},
            execution_metadata={},
        )
    )

    roi = output["roi"]
    assert roi["roi_id"] == "tray-7"
    assert roi["roi_kind"] == "polygon"
    assert roi["bbox_xyxy"] == [10.0, 20.0, 110.0, 80.0]
    assert roi["polygon_xy"] == [[10.0, 20.0], [110.0, 20.0], [110.0, 80.0], [10.0, 80.0]]
    assert roi["area"] == 6000
    assert roi["source_image"]["image_handle"] == "tray-image"
    assert output["summary"]["value"]["point_count"] == 4


def test_contour_to_roi_catalog_contains_node_definition() -> None:
    """验证 contour-to-roi 已写入 OpenCV shape 节点目录。"""

    catalog = build_custom_node_catalog_payload()
    node_type_ids = {
        node_definition["node_type_id"]
        for node_definition in catalog["node_definitions"]
    }

    assert "custom.opencv.contour-to-roi" in node_type_ids


def test_contour_to_roi_outputs_min_area_rect_for_dense_contour() -> None:
    """验证多点 contour 可以通过 min-area-rect 转成四点 ROI。"""

    contours_payload = _build_contours_payload()
    contours_payload["items"][0]["points"] = [
        [10, 30],
        [25, 20],
        [95, 20],
        [110, 30],
        [110, 70],
        [95, 80],
        [25, 80],
        [10, 70],
    ]

    output = handle_node(
        WorkflowNodeExecutionRequest(
            node_id="contour-to-roi",
            node_definition=object(),
            parameters={
                "roi_id_prefix": "tray",
                "display_name_prefix": "Tray",
                "polygon_mode": "min-area-rect",
                "require_quad": True,
            },
            input_values={"contours": contours_payload},
            execution_metadata={},
        )
    )

    roi = output["roi"]
    assert roi["roi_kind"] == "polygon"
    assert len(roi["polygon_xy"]) == 4
    assert output["summary"]["value"]["source_point_count"] == 8
    assert output["summary"]["value"]["point_count"] == 4
    assert output["summary"]["value"]["polygon_mode"] == "min-area-rect"
