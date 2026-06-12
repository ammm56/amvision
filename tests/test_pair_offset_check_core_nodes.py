"""pair-offset-check core 节点测试。"""

from __future__ import annotations

from backend.nodes.core_nodes.pair_offset_check import _pair_offset_check_handler
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_pair_offset_check_passes_expected_pair_vector() -> None:
    """验证 pair-offset-check 可通过符合期望相对偏移的零件对。"""

    output = _pair_offset_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="pair-offset-check",
            node_definition=object(),
            parameters={
                "source_selector": {"class_name": "pin-left", "strategy": "largest-area"},
                "target_selector": {"class_name": "pin-right", "strategy": "largest-area"},
                "expected_dx": 40.0,
                "expected_dy": 4.0,
                "max_abs_dx_error": 2.0,
                "max_abs_dy_error": 2.0,
                "max_distance_error_pixels": 2.0,
            },
            input_values={"regions": _build_regions_payload()},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is True
    metrics_value = output["metrics"]["value"]
    assert metrics_value["selected_source_region_id"] == "region-pin-left"
    assert metrics_value["selected_target_region_id"] == "region-pin-right"
    assert metrics_value["actual_dx"] == 40.0
    assert metrics_value["actual_dy"] == 4.0
    assert metrics_value["dx_error"] == 0.0
    assert metrics_value["dy_error"] == 0.0


def test_pair_offset_check_rejects_pair_with_large_offset_error() -> None:
    """验证 pair-offset-check 会拒绝相对偏移超差的零件对。"""

    output = _pair_offset_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="pair-offset-check",
            node_definition=object(),
            parameters={
                "source_selector": {"class_name": "pin-left", "strategy": "largest-area"},
                "target_selector": {"class_name": "pin-right", "strategy": "largest-area"},
                "expected_dx": 40.0,
                "expected_dy": 0.0,
                "max_abs_dx_error": 1.0,
                "max_abs_dy_error": 1.0,
            },
            input_values={"regions": _build_regions_payload()},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is False
    metrics_value = output["metrics"]["value"]
    assert metrics_value["selected_source_region_id"] == "region-pin-left"
    assert metrics_value["selected_target_region_id"] == "region-pin-right"
    assert metrics_value["dy_error"] == 4.0
    assert "dy-error-too-large" in metrics_value["failure_reasons"]


def _build_regions_payload() -> dict[str, object]:
    """构造双定位销的测试 regions.v1 payload。"""

    return {
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "pair-offset-image",
            "media_type": "image/png",
            "width": 160,
            "height": 120,
        },
        "count": 3,
        "items": [
            {
                "region_id": "region-pin-left",
                "score": 0.97,
                "class_id": 1,
                "class_name": "pin-left",
                "bbox_xyxy": [20.0, 30.0, 28.0, 38.0],
                "polygon_xy": [[20.0, 30.0], [28.0, 30.0], [28.0, 38.0], [20.0, 38.0]],
                "area": 64,
            },
            {
                "region_id": "region-pin-right",
                "score": 0.95,
                "class_id": 2,
                "class_name": "pin-right",
                "bbox_xyxy": [60.0, 34.0, 68.0, 42.0],
                "polygon_xy": [[60.0, 34.0], [68.0, 34.0], [68.0, 42.0], [60.0, 42.0]],
                "area": 64,
            },
            {
                "region_id": "region-bracket",
                "score": 0.9,
                "class_id": 3,
                "class_name": "bracket",
                "bbox_xyxy": [18.0, 22.0, 74.0, 50.0],
                "polygon_xy": [[18.0, 22.0], [74.0, 22.0], [74.0, 50.0], [18.0, 50.0]],
                "area": 1568,
            },
        ],
    }
