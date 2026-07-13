"""Core ROI From Contour 节点测试。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import validate_node_definition_catalog
from backend.nodes.core_catalog import (
    get_core_workflow_node_definitions,
    get_core_workflow_payload_contracts,
)
from backend.nodes.core_nodes.vision.roi.roi_from_contour import _roi_from_contour_handler
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


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


def _build_debug_contours_payload() -> dict[str, object]:
    """构造不需要读取图片内容的 storage-ref 调试 payload。"""

    contours_payload = _build_contours_payload()
    contours_payload["source_image"] = {
        "transport_kind": "storage",
        "object_key": "project/files/tray.jpg",
        "media_type": "image/jpeg",
        "width": 160,
        "height": 120,
    }
    return contours_payload


def test_roi_from_contour_outputs_polygon_roi_for_quad_contour() -> None:
    """验证四点 contour 可以转换为 polygon roi.v1。"""

    output = _roi_from_contour_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-from-contour",
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
    assert output["summary"]["value"]["selected_contour_index"] == 7
    assert output["summary"]["value"]["point_count"] == 4


def test_roi_from_contour_catalog_contains_node_definition() -> None:
    """验证 roi-from-contour 已写入 core 节点目录。"""

    node_type_ids = {node_definition.node_type_id for node_definition in get_core_workflow_node_definitions()}

    assert "core.vision.roi-from-contour" in node_type_ids


def test_core_catalog_contains_contours_payload_contract() -> None:
    """验证 core 节点目录可独立校验 contours.v1 引用。"""

    node_definitions = get_core_workflow_node_definitions()
    payload_contracts = get_core_workflow_payload_contracts()
    payload_type_ids = {contract.payload_type_id for contract in payload_contracts}

    assert "contours.v1" in payload_type_ids
    validate_node_definition_catalog(
        node_definitions=node_definitions,
        payload_contracts=payload_contracts,
    )


def test_roi_from_contour_outputs_min_area_rect_for_dense_contour() -> None:
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

    output = _roi_from_contour_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-from-contour",
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


def test_roi_from_contour_debug_overlay_uses_final_bbox_roi() -> None:
    """验证 bbox 输出时调试图突出显示最终 bbox，而不是原始 contour 多边形。"""

    contours_payload = _build_debug_contours_payload()
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

    output = _roi_from_contour_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-from-contour",
            node_definition=object(),
            parameters={
                "roi_kind": "bbox",
                "polygon_mode": "min-area-rect",
                "require_quad": True,
                "debug_image_panel_enabled": True,
            },
            input_values={"contours": contours_payload},
            execution_metadata={"debug_image_panels_enabled": True},
        )
    )

    selected_overlay = output["debug_preview"]["overlays"][-1]
    assert output["roi"]["roi_kind"] == "bbox"
    assert output["summary"]["value"]["point_count"] == 4
    assert output["summary"]["value"]["candidate_polygon_point_count"] == 4
    assert output["summary"]["value"]["effective_geometry"] == "bbox"
    assert selected_overlay["kind"] == "selected-contour"
    assert selected_overlay["bbox_xyxy"] == [10.0, 20.0, 110.0, 80.0]
    assert "points_xy" not in selected_overlay


def test_roi_from_contour_debug_overlay_uses_min_area_rect_polygon() -> None:
    """验证 min-area-rect polygon 输出时调试图显示四点旋转矩形。"""

    contours_payload = _build_debug_contours_payload()
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

    output = _roi_from_contour_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-from-contour",
            node_definition=object(),
            parameters={
                "roi_kind": "polygon",
                "polygon_mode": "min-area-rect",
                "require_quad": True,
                "debug_image_panel_enabled": True,
            },
            input_values={"contours": contours_payload},
            execution_metadata={"debug_image_panels_enabled": True},
        )
    )

    selected_overlay = output["debug_preview"]["overlays"][-1]
    assert output["roi"]["roi_kind"] == "polygon"
    assert output["summary"]["value"]["point_count"] == 4
    assert output["summary"]["value"]["effective_geometry"] == "min-area-rect"
    assert selected_overlay["kind"] == "selected-contour"
    assert len(selected_overlay["points_xy"]) == 4
    assert "bbox_xyxy" not in selected_overlay


def test_roi_from_contour_selects_by_contour_payload_index() -> None:
    """验证显式选择使用 contours.v1 的真实 contour_index，而不是 items 下标。"""

    contours_payload = _build_contours_payload()
    contours_payload["items"].append(
        {
            "contour_index": 12,
            "point_count": 4,
            "bbox_xyxy": [30, 40, 70, 90],
            "points": [[30, 40], [70, 40], [70, 90], [30, 90]],
        }
    )

    output = _roi_from_contour_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-from-contour",
            node_definition=object(),
            parameters={"selected_contour_index": 12, "roi_id_prefix": "slot"},
            input_values={"contours": contours_payload},
            execution_metadata={},
        )
    )

    assert output["roi"]["roi_id"] == "slot-12"
    assert output["roi"]["bbox_xyxy"] == [30.0, 40.0, 70.0, 90.0]
    assert output["summary"]["value"]["selected_contour_index"] == 12
