"""multi-part-presence-check core 节点测试。"""

from __future__ import annotations

from backend.nodes.core_nodes.multi_part_presence_check import _multi_part_presence_check_handler
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_multi_part_presence_check_passes_required_parts() -> None:
    """验证多部件存在性检查可通过完整装配集合。"""

    output = _multi_part_presence_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="multi-part-presence-check",
            node_definition=object(),
            parameters={
                "match_mode": "all",
                "requirements": [
                    {"part_name": "left-screw", "class_name": "screw", "min_count": 2, "max_count": 2},
                    {"part_name": "main-gasket", "class_name": "gasket", "min_count": 1, "max_count": 1},
                ],
            },
            input_values={"regions": _build_regions_payload()},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is True
    metrics_value = output["metrics"]["value"]
    assert metrics_value["passed_part_count"] == 2
    assert metrics_value["failed_part_count"] == 0
    assert metrics_value["passed_part_names"] == ["left-screw", "main-gasket"]


def test_multi_part_presence_check_rejects_missing_or_extra_parts() -> None:
    """验证多部件存在性检查会指出缺件与超件。"""

    output = _multi_part_presence_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="multi-part-presence-check",
            node_definition=object(),
            parameters={
                "match_mode": "all",
                "requirements": [
                    {"part_name": "left-screw", "class_name": "screw", "min_count": 1, "max_count": 1},
                    {"part_name": "safety-clip", "class_name": "clip", "min_count": 1, "max_count": 1},
                ],
            },
            input_values={"regions": _build_regions_payload()},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is False
    metrics_value = output["metrics"]["value"]
    assert metrics_value["failed_part_count"] == 2
    left_screw_item = metrics_value["items"][0]
    safety_clip_item = metrics_value["items"][1]
    assert left_screw_item["matched_count"] == 2
    assert "too-many-parts" in left_screw_item["failure_reasons"]
    assert safety_clip_item["matched_count"] == 0
    assert "missing-required-parts" in safety_clip_item["failure_reasons"]


def _build_regions_payload() -> dict[str, object]:
    """构造装配检测结果的测试 regions.v1 payload。"""

    return {
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "multi-part-presence-image",
            "media_type": "image/png",
            "width": 160,
            "height": 120,
        },
        "count": 3,
        "items": [
            {
                "region_id": "region-screw-1",
                "score": 0.96,
                "class_id": 1,
                "class_name": "screw",
                "bbox_xyxy": [12.0, 24.0, 20.0, 32.0],
                "polygon_xy": [[12.0, 24.0], [20.0, 24.0], [20.0, 32.0], [12.0, 32.0]],
                "area": 64,
            },
            {
                "region_id": "region-screw-2",
                "score": 0.94,
                "class_id": 1,
                "class_name": "screw",
                "bbox_xyxy": [28.0, 24.0, 36.0, 32.0],
                "polygon_xy": [[28.0, 24.0], [36.0, 24.0], [36.0, 32.0], [28.0, 32.0]],
                "area": 64,
            },
            {
                "region_id": "region-gasket-1",
                "score": 0.91,
                "class_id": 2,
                "class_name": "gasket",
                "bbox_xyxy": [52.0, 18.0, 104.0, 58.0],
                "polygon_xy": [[52.0, 18.0], [104.0, 18.0], [104.0, 58.0], [52.0, 58.0]],
                "area": 2080,
            },
        ],
    }
