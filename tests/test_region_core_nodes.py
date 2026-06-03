"""region / roi core 节点轻量回归测试。"""

from __future__ import annotations

from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from backend.nodes.core_nodes.regions_area_ratio import _regions_area_ratio_handler
from backend.nodes.core_nodes.regions_area_sum import _regions_area_sum_handler
from backend.nodes.core_nodes.regions_bbox_metrics import _regions_bbox_metrics_handler
from backend.nodes.core_nodes.regions_count import _regions_count_handler
from backend.nodes.core_nodes.regions_coverage_check import _regions_coverage_check_handler
from backend.nodes.core_nodes.regions_filter import _regions_filter_handler
from backend.nodes.core_nodes.regions_inside_check import _regions_inside_check_handler
from backend.nodes.core_nodes.regions_intersection_metrics import _regions_intersection_metrics_handler
from backend.nodes.core_nodes.regions_offset_check import _regions_offset_check_handler
from backend.nodes.core_nodes.roi_create import _roi_create_handler
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_core_catalog_contains_roi_payload_contract() -> None:
    """验证 core catalog 已公开 roi.v1 contract。"""

    payload_type_ids = {contract.payload_type_id for contract in get_core_workflow_payload_contracts()}

    assert "roi.v1" in payload_type_ids


def test_regions_filter_count_and_area_sum_handlers() -> None:
    """验证第一批基础 regions 统计节点可按预期输出。"""

    regions_payload = _build_regions_payload()

    filter_output = _regions_filter_handler(
        WorkflowNodeExecutionRequest(
            node_id="regions-filter",
            node_definition=object(),
            parameters={"min_score": 0.8, "class_names": ["defect-a"]},
            input_values={"regions": regions_payload},
            execution_metadata={},
        )
    )

    assert filter_output["regions"]["count"] == 1
    assert filter_output["summary"]["value"]["filtered_count"] == 1

    count_output = _regions_count_handler(
        WorkflowNodeExecutionRequest(
            node_id="regions-count",
            node_definition=object(),
            parameters={},
            input_values={"regions": regions_payload},
            execution_metadata={},
        )
    )
    assert count_output["value"]["value"] == 2

    area_sum_output = _regions_area_sum_handler(
        WorkflowNodeExecutionRequest(
            node_id="regions-area-sum",
            node_definition=object(),
            parameters={},
            input_values={"regions": regions_payload},
            execution_metadata={},
        )
    )
    assert area_sum_output["value"]["value"] == 32


def test_regions_area_ratio_and_bbox_metrics_handlers() -> None:
    """验证面积占比和 bbox 派生指标输出。"""

    regions_payload = _build_regions_payload()

    area_ratio_output = _regions_area_ratio_handler(
        WorkflowNodeExecutionRequest(
            node_id="regions-area-ratio",
            node_definition=object(),
            parameters={},
            input_values={"regions": regions_payload},
            execution_metadata={},
        )
    )

    assert area_ratio_output["value"]["value"] == 32 / 200

    bbox_output = _regions_bbox_metrics_handler(
        WorkflowNodeExecutionRequest(
            node_id="regions-bbox-metrics",
            node_definition=object(),
            parameters={},
            input_values={"regions": regions_payload},
            execution_metadata={},
        )
    )

    metrics_value = bbox_output["value"]["value"]
    assert metrics_value["count"] == 2
    assert metrics_value["items"][0]["width"] == 4.0
    assert metrics_value["items"][0]["height"] == 4.0


def test_roi_create_bbox_handler_returns_roi_payload() -> None:
    """验证 roi-create 可生成 bbox ROI。"""

    output = _roi_create_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-create",
            node_definition=object(),
            parameters={"roi_kind": "bbox", "roi_id": "roi-a", "bbox_xyxy": [0, 0, 10, 10]},
            input_values={},
            execution_metadata={},
        )
    )

    assert output["roi"]["roi_id"] == "roi-a"
    assert output["roi"]["roi_kind"] == "bbox"
    assert output["roi"]["area"] == 100
    assert output["summary"]["value"]["bbox_xyxy"] == [0.0, 0.0, 10.0, 10.0]


def test_regions_intersection_metrics_returns_expected_values() -> None:
    """验证 ROI 交集与覆盖率指标计算。"""

    output = _regions_intersection_metrics_handler(
        WorkflowNodeExecutionRequest(
            node_id="intersection",
            node_definition=object(),
            parameters={},
            input_values={
                "regions": _build_regions_payload(single=True),
                "roi": _build_roi_payload(),
            },
            execution_metadata={},
        )
    )

    metrics_value = output["value"]["value"]
    assert metrics_value["roi_area"] == 100
    assert metrics_value["union_intersection_area"] == 25
    assert metrics_value["roi_coverage_ratio"] == 0.25
    assert metrics_value["best_inside_ratio"] == 1.0


def test_regions_coverage_check_uses_roi_ratio_threshold() -> None:
    """验证 coverage-check 按 ROI 覆盖率阈值输出布尔结果。"""

    output = _regions_coverage_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="coverage-check",
            node_definition=object(),
            parameters={"min_ratio": 0.15, "max_ratio": 0.2},
            
            input_values={
                "regions": _build_regions_payload(single=True),
                "roi": _build_roi_payload(),
            },
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is False
    assert output["metrics"]["value"]["roi_coverage_ratio"] == 0.25


def test_regions_inside_check_supports_all_mode() -> None:
    """验证 inside-check 可按 all 模式检查所有区域是否完全在 ROI 内。"""

    output = _regions_inside_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="inside-check",
            node_definition=object(),
            parameters={"match_mode": "all", "min_inside_ratio": 1.0},
            input_values={
                "regions": _build_regions_payload(),
                "roi": _build_roi_payload(),
            },
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is False
    assert output["metrics"]["value"]["matched_count"] == 1


def test_regions_offset_check_reports_selected_region_offset() -> None:
    """验证 offset-check 会按策略选择目标并输出偏移结果。"""

    output = _regions_offset_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="offset-check",
            node_definition=object(),
            parameters={"strategy": "largest-area", "max_distance_pixels": 3.0},
            input_values={
                "regions": _build_regions_payload(single=True),
                "roi": _build_roi_payload(),
            },
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is True
    assert output["metrics"]["value"]["selected_region_id"] == "region-1"
    assert output["metrics"]["value"]["distance_pixels"] > 0


def _build_regions_payload(*, single: bool = False) -> dict[str, object]:
    """构造测试用 regions.v1 payload。"""

    items = [
        {
            "region_id": "region-1",
            "score": 0.92,
            "class_id": 1,
            "class_name": "defect-a",
            "bbox_xyxy": [2.0, 2.0, 6.0, 6.0],
            "polygon_xy": [[2.0, 2.0], [6.0, 2.0], [6.0, 6.0], [2.0, 6.0]],
            "area": 16,
            "prompt_id": "prompt-a",
            "state": "tracked",
        },
        {
            "region_id": "region-2",
            "score": 0.55,
            "class_id": 2,
            "class_name": "defect-b",
            "bbox_xyxy": [12.0, 2.0, 16.0, 6.0],
            "polygon_xy": [[12.0, 2.0], [16.0, 2.0], [16.0, 6.0], [12.0, 6.0]],
            "area": 16,
            "prompt_id": "prompt-b",
            "state": "candidate",
        },
    ]
    if single:
        items = items[:1]
    return {
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "image-a",
            "media_type": "image/png",
            "width": 20,
            "height": 10,
        },
        "count": len(items),
        "items": items,
    }


def _build_roi_payload() -> dict[str, object]:
    """构造测试用 roi.v1 payload。"""

    return {
        "roi_id": "roi-main",
        "roi_kind": "bbox",
        "bbox_xyxy": [0.0, 0.0, 10.0, 10.0],
        "polygon_xy": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
        "area": 100,
    }
