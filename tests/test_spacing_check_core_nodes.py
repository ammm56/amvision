"""spacing-check core 节点测试。"""

from __future__ import annotations

from backend.nodes.core_nodes.vision.geometry.spacing_check import _spacing_check_handler
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_spacing_check_passes_same_class_horizontal_center_spacing() -> None:
    """验证 spacing-check 可用 leftmost/rightmost 检查同类目标中心距。"""

    output = _spacing_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="spacing-check",
            node_definition=object(),
            parameters={
                "source_selector": {"class_name": "mount-hole", "strategy": "leftmost"},
                "target_selector": {"class_name": "mount-hole", "strategy": "rightmost"},
                "spacing_mode": "center-x",
                "expected_spacing": 32.0,
                "max_abs_spacing_error": 1.0,
            },
            input_values={"regions": _build_regions_payload()},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is True
    metrics_value = output["metrics"]["value"]
    assert metrics_value["selected_source_region_id"] == "region-hole-left"
    assert metrics_value["selected_target_region_id"] == "region-hole-right"
    assert metrics_value["actual_spacing"] == 32.0
    assert metrics_value["spacing_error"] == 0.0


def test_spacing_check_rejects_edge_gap_out_of_tolerance() -> None:
    """验证 spacing-check 会拒绝边间距超差。"""

    output = _spacing_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="spacing-check",
            node_definition=object(),
            parameters={
                "source_selector": {"class_name": "mount-hole", "strategy": "leftmost"},
                "target_selector": {"class_name": "mount-hole", "strategy": "rightmost"},
                "spacing_mode": "edge-gap-x",
                "expected_spacing": 28.0,
                "max_abs_spacing_error": 1.0,
            },
            input_values={"regions": _build_regions_payload()},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is False
    metrics_value = output["metrics"]["value"]
    assert metrics_value["actual_spacing"] == 24.0
    assert metrics_value["spacing_error"] == -4.0
    assert "spacing-error-too-large" in metrics_value["failure_reasons"]


def _build_regions_payload() -> dict[str, object]:
    """构造双安装孔的测试 regions.v1 payload。"""

    return {
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "spacing-check-image",
            "media_type": "image/png",
            "width": 160,
            "height": 100,
        },
        "count": 3,
        "items": [
            {
                "region_id": "region-hole-left",
                "score": 0.97,
                "class_id": 1,
                "class_name": "mount-hole",
                "bbox_xyxy": [20.0, 20.0, 28.0, 28.0],
                "polygon_xy": [[20.0, 20.0], [28.0, 20.0], [28.0, 28.0], [20.0, 28.0]],
                "area": 64,
            },
            {
                "region_id": "region-hole-right",
                "score": 0.96,
                "class_id": 1,
                "class_name": "mount-hole",
                "bbox_xyxy": [52.0, 20.0, 60.0, 28.0],
                "polygon_xy": [[52.0, 20.0], [60.0, 20.0], [60.0, 28.0], [52.0, 28.0]],
                "area": 64,
            },
            {
                "region_id": "region-bracket-body",
                "score": 0.9,
                "class_id": 2,
                "class_name": "bracket-body",
                "bbox_xyxy": [14.0, 14.0, 66.0, 38.0],
                "polygon_xy": [[14.0, 14.0], [66.0, 14.0], [66.0, 38.0], [14.0, 38.0]],
                "area": 1248,
            },
        ],
    }
