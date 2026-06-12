"""reference-mark-align-check core 节点测试。"""

from __future__ import annotations

from backend.nodes.core_nodes.reference_mark_align_check import _reference_mark_align_check_handler
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_reference_mark_align_check_passes_expected_mark_alignment() -> None:
    """验证 reference-mark-align-check 可通过符合期望对位偏移的标记。"""

    output = _reference_mark_align_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="reference-mark-align-check",
            node_definition=object(),
            parameters={
                "reference_selector": {"class_name": "reference-hole", "strategy": "largest-area"},
                "mark_selector": {"class_name": "print-mark", "strategy": "largest-area"},
                "expected_dx": 24.0,
                "expected_dy": 3.0,
                "max_abs_dx_error": 1.0,
                "max_abs_dy_error": 1.0,
                "max_distance_error_pixels": 1.0,
            },
            input_values={"regions": _build_regions_payload()},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is True
    metrics_value = output["metrics"]["value"]
    assert metrics_value["selected_reference_region_id"] == "region-reference-hole"
    assert metrics_value["selected_mark_region_id"] == "region-print-mark"
    assert metrics_value["actual_dx"] == 24.0
    assert metrics_value["actual_dy"] == 3.0


def test_reference_mark_align_check_rejects_large_alignment_error() -> None:
    """验证 reference-mark-align-check 会拒绝偏移超差的标记对位。"""

    output = _reference_mark_align_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="reference-mark-align-check",
            node_definition=object(),
            parameters={
                "reference_selector": {"class_name": "reference-hole", "strategy": "largest-area"},
                "mark_selector": {"class_name": "print-mark", "strategy": "largest-area"},
                "expected_dx": 20.0,
                "expected_dy": 3.0,
                "max_abs_dx_error": 1.0,
                "max_abs_dy_error": 1.0,
            },
            input_values={"regions": _build_regions_payload()},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is False
    metrics_value = output["metrics"]["value"]
    assert metrics_value["dx_error"] == 4.0
    assert "dx-error-too-large" in metrics_value["failure_reasons"]


def _build_regions_payload() -> dict[str, object]:
    """构造参考孔与印刷标记的测试 regions.v1 payload。"""

    return {
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "reference-mark-align-image",
            "media_type": "image/png",
            "width": 180,
            "height": 120,
        },
        "count": 3,
        "items": [
            {
                "region_id": "region-reference-hole",
                "score": 0.98,
                "class_id": 1,
                "class_name": "reference-hole",
                "bbox_xyxy": [18.0, 26.0, 26.0, 34.0],
                "polygon_xy": [[18.0, 26.0], [26.0, 26.0], [26.0, 34.0], [18.0, 34.0]],
                "area": 64,
            },
            {
                "region_id": "region-print-mark",
                "score": 0.95,
                "class_id": 2,
                "class_name": "print-mark",
                "bbox_xyxy": [42.0, 29.0, 50.0, 37.0],
                "polygon_xy": [[42.0, 29.0], [50.0, 29.0], [50.0, 37.0], [42.0, 37.0]],
                "area": 64,
            },
            {
                "region_id": "region-label-body",
                "score": 0.9,
                "class_id": 3,
                "class_name": "label-body",
                "bbox_xyxy": [34.0, 18.0, 112.0, 62.0],
                "polygon_xy": [[34.0, 18.0], [112.0, 18.0], [112.0, 62.0], [34.0, 62.0]],
                "area": 3432,
            },
        ],
    }
