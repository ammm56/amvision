"""ROI 网格与数组摘要基础节点测试。"""

from __future__ import annotations

from backend.nodes.core_catalog import get_core_workflow_node_definitions
from backend.nodes.core_nodes.logic.collections.array_summary import _array_summary_handler
from backend.nodes.core_nodes.logic.value.payload_to_value import _payload_to_value_handler
from backend.nodes.core_nodes.logic.value.value_to_roi import _value_to_roi_handler
from backend.nodes.core_nodes.vision.roi.roi_grid_create import _roi_grid_create_handler
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_core_catalog_contains_roi_grid_nodes() -> None:
    """验证新增通用基础节点已经进入 core catalog。"""

    node_type_ids = {node.node_type_id for node in get_core_workflow_node_definitions()}

    assert "core.vision.roi-grid-create" in node_type_ids
    assert "core.logic.value-to-roi" in node_type_ids
    assert "core.logic.array-summary" in node_type_ids


def test_roi_grid_create_generates_row_major_roi_values() -> None:
    """验证 ROI Grid Create 可按行优先生成稳定 ROI 列表。"""

    output = _roi_grid_create_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-grid-create",
            node_definition=object(),
            parameters={
                "rows": 2,
                "columns": 3,
                "origin_x": 10,
                "origin_y": 20,
                "roi_width": 5,
                "roi_height": 4,
                "step_x": 7,
                "step_y": 9,
                "roi_id_prefix": "slot",
            },
            input_values={
                "image": {
                    "transport_kind": "memory",
                    "image_handle": "image-a",
                    "media_type": "image/bgr24",
                    "width": 100,
                    "height": 80,
                }
            },
            execution_metadata={},
        )
    )

    roi_items = output["value"]["value"]
    assert len(roi_items) == 6
    assert roi_items[0]["roi_id"] == "slot-01-01"
    assert roi_items[0]["bbox_xyxy"] == [10.0, 20.0, 15.0, 24.0]
    assert roi_items[-1]["roi_id"] == "slot-02-03"
    assert roi_items[-1]["bbox_xyxy"] == [24.0, 29.0, 29.0, 33.0]
    assert roi_items[0]["source_image"]["image_handle"] == "image-a"
    assert output["summary"]["value"]["count"] == 6


def test_value_to_roi_restores_roi_payload_from_nested_value() -> None:
    """验证 Value To ROI 可从 value.v1 的嵌套字段恢复 roi.v1。"""

    output = _value_to_roi_handler(
        WorkflowNodeExecutionRequest(
            node_id="value-to-roi",
            node_definition=object(),
            parameters={"path": "current"},
            input_values={
                "value": {
                    "value": {
                        "current": {
                            "roi_id": "slot-01-02",
                            "roi_kind": "bbox",
                            "bbox_xyxy": [1, 2, 11, 12],
                            "polygon_xy": [[1, 2], [11, 2], [11, 12], [1, 12]],
                            "area": 100,
                        }
                    }
                },
                "image": {
                    "transport_kind": "memory",
                    "image_handle": "image-b",
                    "media_type": "image/bgr24",
                    "width": 20,
                    "height": 20,
                },
            },
            execution_metadata={},
        )
    )

    assert output["roi"]["roi_id"] == "slot-01-02"
    assert output["roi"]["source_image"]["image_handle"] == "image-b"
    assert output["summary"]["value"]["source_image_attached"] is True


def test_array_summary_reports_truthy_and_numeric_metrics() -> None:
    """验证 Array Summary 可汇总布尔结果和数值统计。"""

    output = _array_summary_handler(
        WorkflowNodeExecutionRequest(
            node_id="array-summary",
            node_definition=object(),
            parameters={"path": "passed"},
            input_values={
                "items": {
                    "value": [
                        {"passed": True, "score": 0.9},
                        {"passed": False, "score": 0.2},
                        {"passed": True, "score": 0.8},
                    ]
                }
            },
            execution_metadata={},
        )
    )

    summary = output["summary"]["value"]
    assert summary["selected_count"] == 3
    assert summary["truthy_count"] == 2
    assert summary["falsey_count"] == 1
    assert output["all"]["value"] is False
    assert output["any"]["value"] is True


def test_payload_to_value_wraps_boolean_payload_value() -> None:
    """验证 Payload To Value 可把 boolean.v1 转成普通布尔 value。"""

    output = _payload_to_value_handler(
        WorkflowNodeExecutionRequest(
            node_id="payload-to-value",
            node_definition=object(),
            parameters={},
            input_values={"boolean": {"value": True}},
            execution_metadata={},
        )
    )

    assert output["value"]["value"] is True
