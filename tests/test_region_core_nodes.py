"""region / roi core 节点轻量回归测试。"""

from __future__ import annotations

from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from backend.nodes.core_nodes.detections_to_regions import (
    _detections_to_regions_handler,
)
from backend.nodes.core_nodes.regions_area_ratio import _regions_area_ratio_handler
from backend.nodes.core_nodes.regions_area_sum import _regions_area_sum_handler
from backend.nodes.core_nodes.regions_bbox_metrics import _regions_bbox_metrics_handler
from backend.nodes.core_nodes.regions_count import _regions_count_handler
from backend.nodes.core_nodes.regions_coverage_check import (
    _regions_coverage_check_handler,
)
from backend.nodes.core_nodes.regions_filter import _regions_filter_handler
from backend.nodes.core_nodes.regions_inside_check import _regions_inside_check_handler
from backend.nodes.core_nodes.regions_intersection_metrics import (
    _regions_intersection_metrics_handler,
)
from backend.nodes.core_nodes.regions_offset_check import _regions_offset_check_handler
from backend.nodes.core_nodes.roi_create import _roi_create_handler
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def test_core_catalog_contains_roi_payload_contract() -> None:
    """验证 core catalog 已公开 roi.v1 contract。"""

    payload_type_ids = {
        contract.payload_type_id for contract in get_core_workflow_payload_contracts()
    }

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


def test_detections_to_regions_handler_converts_detection_boxes() -> None:
    """验证 detections-to-regions 可把 bbox 检测结果转成标准 regions.v1。"""

    output = _detections_to_regions_handler(
        WorkflowNodeExecutionRequest(
            node_id="detections-to-regions",
            node_definition=object(),
            parameters={},
            input_values={
                "detections": {
                    "items": [
                        {
                            "bbox_xyxy": [2.0, 3.0, 8.0, 9.0],
                            "score": 0.91,
                            "class_id": 4,
                            "class_name": "part-a",
                            "detection_id": "det-a",
                        }
                    ]
                },
                "image": {
                    "transport_kind": "memory",
                    "image_handle": "image-a",
                    "media_type": "image/png",
                    "width": 20,
                    "height": 12,
                },
            },
            execution_metadata={},
        )
    )

    regions_payload = output["regions"]
    assert regions_payload["count"] == 1
    assert regions_payload["source_image"]["transport_kind"] == "memory"
    assert regions_payload["items"][0]["region_id"] == "det-a"
    assert regions_payload["items"][0]["class_id"] == 4
    assert regions_payload["items"][0]["class_name"] == "part-a"
    assert regions_payload["items"][0]["polygon_xy"] == [
        [2.0, 3.0],
        [8.0, 3.0],
        [8.0, 9.0],
        [2.0, 9.0],
    ]
    assert regions_payload["items"][0]["area"] == 36
    assert output["summary"]["value"]["source_image_attached"] is True


def test_detections_to_regions_handler_applies_default_class_fields() -> None:
    """验证 detections-to-regions 会为缺失类别字段补默认值。"""

    output = _detections_to_regions_handler(
        WorkflowNodeExecutionRequest(
            node_id="detections-to-regions",
            node_definition=object(),
            parameters={
                "region_id_prefix": "gate",
                "class_id_default": 9,
                "class_name_default": "unknown-part",
            },
            input_values={
                "detections": {
                    "items": [
                        {
                            "bbox_xyxy": [10.0, 10.0, 14.0, 16.0],
                            "score": 0.77,
                        }
                    ]
                }
            },
            execution_metadata={},
        )
    )

    region_item = output["regions"]["items"][0]
    assert region_item["region_id"] == "gate-1"
    assert region_item["class_id"] == 9
    assert region_item["class_name"] == "unknown-part"
    assert output["summary"]["value"]["class_distribution"] == {"unknown-part": 1}


def test_roi_create_bbox_handler_returns_roi_payload() -> None:
    """验证 roi-create 可生成 bbox ROI。"""

    output = _roi_create_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-create",
            node_definition=object(),
            parameters={
                "roi_kind": "bbox",
                "roi_id": "roi-a",
                "bbox_xyxy": [0, 0, 10, 10],
            },
            input_values={},
            execution_metadata={},
        )
    )

    assert output["roi"]["roi_id"] == "roi-a"
    assert output["roi"]["roi_kind"] == "bbox"
    assert output["roi"]["area"] == 100
    assert output["summary"]["value"]["bbox_xyxy"] == [0.0, 0.0, 10.0, 10.0]


def test_roi_create_value_input_overrides_bbox_parameters() -> None:
    """验证 roi-create 可通过 value.v1 动态覆盖默认 bbox ROI。"""

    output = _roi_create_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-create",
            node_definition=object(),
            parameters={
                "roi_kind": "bbox",
                "roi_id": "roi-default",
                "bbox_xyxy": [0, 0, 10, 10],
            },
            input_values={
                "value": {
                    "value": {
                        "roi_id": "roi-runtime",
                        "bbox_xyxy": [3, 4, 13, 14],
                        "display_name": "Runtime ROI",
                    }
                }
            },
            execution_metadata={},
        )
    )

    assert output["roi"]["roi_id"] == "roi-runtime"
    assert output["roi"]["bbox_xyxy"] == [3.0, 4.0, 13.0, 14.0]
    assert output["roi"]["display_name"] == "Runtime ROI"
    assert output["summary"]["value"]["source_kind"] == "value-input"


def test_roi_create_value_input_infers_polygon_kind() -> None:
    """验证 roi-create 可从 value.v1 的 polygon_xy 自动推断 polygon ROI。"""

    output = _roi_create_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-create",
            node_definition=object(),
            parameters={},
            input_values={
                "value": {
                    "value": {
                        "roi_id": "roi-poly",
                        "polygon_xy": [[0, 0], [10, 0], [10, 8], [0, 8]],
                    }
                }
            },
            execution_metadata={},
        )
    )

    assert output["roi"]["roi_id"] == "roi-poly"
    assert output["roi"]["roi_kind"] == "polygon"
    assert output["roi"]["bbox_xyxy"] == [0.0, 0.0, 10.0, 8.0]
    assert output["roi"]["area"] == 80


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
