"""ROI 网格与数组摘要基础节点测试。"""

from __future__ import annotations

from backend.nodes.core_catalog import get_core_workflow_node_definitions
from backend.nodes.core_nodes.logic.collections.array_summary import _array_summary_handler
from backend.nodes.core_nodes.logic.value.payload_to_value import _payload_to_value_handler
from backend.nodes.core_nodes.logic.value.value_to_image_ref import _value_to_image_ref_handler
from backend.nodes.core_nodes.logic.value.value_to_roi import _value_to_roi_handler
from backend.nodes.core_nodes.io.image.image_refs_to_value_list import _image_refs_to_value_list_handler
from backend.nodes.core_nodes.io.preview.value_preview import _value_preview_handler
from backend.nodes.core_nodes.model.deployment.classification_results_summary import (
    _classification_results_summary_handler,
)
from backend.nodes.core_nodes.vision.roi.roi_grid_create import (
    _build_roi_grid_overlays,
    _roi_grid_create_handler,
)
from backend.nodes.core_nodes.vision.roi.roi_list_create import _roi_list_create_handler
from backend.nodes.core_nodes.vision.roi.roi_list_item_get import _roi_list_item_get_handler
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_core_catalog_contains_roi_grid_nodes() -> None:
    """验证新增通用基础节点已经进入 core catalog。"""

    node_type_ids = {node.node_type_id for node in get_core_workflow_node_definitions()}

    assert "core.vision.roi-grid-create" in node_type_ids
    assert "core.vision.roi-list-create" in node_type_ids
    assert "core.vision.roi-list-item-get" in node_type_ids
    assert "core.logic.value-to-roi" in node_type_ids
    assert "core.logic.value-to-image-ref" in node_type_ids
    assert "core.io.image-refs-to-value-list" in node_type_ids
    assert "core.model.classification-results-summary" in node_type_ids
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

    roi_items = output["rois"]["items"]
    assert len(roi_items) == 6
    assert output["rois"]["count"] == 6
    assert roi_items[0]["roi_id"] == "slot-01-01"
    assert roi_items[0]["bbox_xyxy"] == [10.0, 20.0, 15.0, 24.0]
    assert roi_items[-1]["roi_id"] == "slot-02-03"
    assert roi_items[-1]["bbox_xyxy"] == [24.0, 29.0, 29.0, 33.0]
    assert roi_items[0]["source_image"]["image_handle"] == "image-a"
    assert output["summary"]["value"]["count"] == 6


def test_roi_grid_create_keeps_chinese_display_name_out_of_overlay_label() -> None:
    """验证中文 display_name 保留在数据里，但图像 overlay 使用 OpenCV 可绘制的 ROI ID。"""

    output = _roi_grid_create_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-grid-create",
            node_definition=object(),
            parameters={
                "rows": 1,
                "columns": 1,
                "origin_x": 10,
                "origin_y": 20,
                "roi_width": 30,
                "roi_height": 40,
                "roi_id_prefix": "slot",
                "display_name_prefix": "槽位",
            },
            input_values={},
            execution_metadata={},
        )
    )

    roi_item = output["rois"]["items"][0]
    overlays = _build_roi_grid_overlays([roi_item])

    assert roi_item["display_name"] == "槽位 1-1"
    assert overlays[0]["label"] == "slot-01-01"
    assert "?" not in overlays[0]["label"]


def test_roi_grid_create_uses_defaults_for_blank_parameters_with_source_image() -> None:
    """验证空参数会回退到常用默认值，避免新建节点 Preview Run 被空值阻断。"""

    output = _roi_grid_create_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-grid-create",
            node_definition=object(),
            parameters={
                "rows": "",
                "columns": "",
                "roi_width": "",
                "roi_height": "",
                "step_x": "",
                "step_y": "",
                "roi_id_prefix": "",
            },
            input_values={
                "image": {
                    "transport_kind": "memory",
                    "image_handle": "image-defaults",
                    "media_type": "image/bgr24",
                    "width": 640,
                    "height": 480,
                }
            },
            execution_metadata={},
        )
    )

    roi_items = output["rois"]["items"]
    assert len(roi_items) == 1
    assert roi_items[0]["roi_id"] == "roi-01-01"
    assert roi_items[0]["bbox_xyxy"] == [0.0, 0.0, 640.0, 480.0]
    assert output["summary"]["value"]["rows"] == 1
    assert output["summary"]["value"]["columns"] == 1
    assert output["summary"]["value"]["roi_width"] == 640.0
    assert output["summary"]["value"]["roi_height"] == 480.0


def test_roi_list_create_merges_single_and_value_list_inputs() -> None:
    """验证 ROI List Create 可合并多路 roi.v1 和 value.v1 ROI 数组。"""

    output = _roi_list_create_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-list-create",
            node_definition=object(),
            parameters={"path": "items"},
            input_values={
                "roi": (
                    {
                        "roi_id": "slot-a",
                        "roi_kind": "bbox",
                        "bbox_xyxy": [0, 0, 10, 10],
                        "polygon_xy": [[0, 0], [10, 0], [10, 10], [0, 10]],
                        "area": 100,
                    },
                ),
                "rois": {
                    "format_id": "amvision.roi-list.v1",
                    "items": [
                        {
                            "roi_id": "slot-c",
                            "roi_kind": "bbox",
                            "bbox_xyxy": [50, 20, 60, 30],
                            "polygon_xy": [[50, 20], [60, 20], [60, 30], [50, 30]],
                            "area": 100,
                        }
                    ],
                    "count": 1,
                },
                "items": {
                    "value": {
                        "items": [
                            {
                                "roi_id": "slot-b",
                                "roi_kind": "polygon",
                                "bbox_xyxy": [20, 20, 40, 42],
                                "polygon_xy": [[20, 20], [40, 20], [36, 42], [22, 38]],
                                "area": 380,
                            }
                        ]
                    }
                },
                "image": {
                    "transport_kind": "memory",
                    "image_handle": "image-list",
                    "media_type": "image/bgr24",
                    "width": 80,
                    "height": 60,
                },
            },
            execution_metadata={},
        )
    )

    roi_items = output["rois"]["items"]
    assert [item["roi_id"] for item in roi_items] == ["slot-a", "slot-c", "slot-b"]
    assert roi_items[0]["source_image"]["image_handle"] == "image-list"
    assert roi_items[1]["source_image"]["image_handle"] == "image-list"
    assert roi_items[2]["source_image"]["image_handle"] == "image-list"
    assert output["summary"]["value"]["count"] == 3


def test_roi_list_item_get_selects_single_roi_from_roi_list() -> None:
    """验证 ROI List Item Get 可从 roi-list.v1 中取出单个 roi.v1。"""

    output = _roi_list_item_get_handler(
        WorkflowNodeExecutionRequest(
            node_id="roi-list-item-get",
            node_definition=object(),
            parameters={"index": -1, "allow_negative": True},
            input_values={
                "rois": {
                    "format_id": "amvision.roi-list.v1",
                    "items": [
                        {
                            "roi_id": "slot-01",
                            "roi_kind": "bbox",
                            "bbox_xyxy": [0, 0, 10, 10],
                            "polygon_xy": [[0, 0], [10, 0], [10, 10], [0, 10]],
                            "area": 100,
                        },
                        {
                            "roi_id": "slot-02",
                            "roi_kind": "bbox",
                            "bbox_xyxy": [20, 0, 30, 10],
                            "polygon_xy": [[20, 0], [30, 0], [30, 10], [20, 10]],
                            "area": 100,
                        },
                    ],
                    "count": 2,
                }
            },
            execution_metadata={},
        )
    )

    assert output["roi"]["roi_id"] == "slot-02"
    assert output["summary"]["value"]["index"] == -1
    assert output["summary"]["value"]["normalized_index"] == 1


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


def test_value_preview_accepts_single_roi_payload() -> None:
    """验证 Value Preview 可直接预览单个 roi.v1。"""

    output = _value_preview_handler(
        WorkflowNodeExecutionRequest(
            node_id="value-preview-roi",
            node_definition=object(),
            parameters={"title": "ROI Preview"},
            input_values={
                "roi": {
                    "roi_id": "slot-preview",
                    "roi_kind": "bbox",
                    "bbox_xyxy": [1, 2, 11, 12],
                    "polygon_xy": [[1, 2], [11, 2], [11, 12], [1, 12]],
                    "area": 100,
                }
            },
            execution_metadata={},
        )
    )

    body = output["body"]
    assert body["type"] == "value-preview"
    assert body["title"] == "ROI Preview"
    assert body["value"]["roi_id"] == "slot-preview"


def test_value_preview_accepts_roi_list_payload() -> None:
    """验证 Value Preview 可预览 roi-list.v1 ROI 列表。"""

    output = _value_preview_handler(
        WorkflowNodeExecutionRequest(
            node_id="value-preview-rois",
            node_definition=object(),
            parameters={"path": "0.roi_id"},
            input_values={
                "rois": {
                    "format_id": "amvision.roi-list.v1",
                    "items": [
                        {
                            "roi_id": "slot-list",
                            "roi_kind": "bbox",
                            "bbox_xyxy": [0, 0, 10, 10],
                            "polygon_xy": [[0, 0], [10, 0], [10, 10], [0, 10]],
                            "area": 100,
                        }
                    ],
                    "count": 1,
                }
            },
            execution_metadata={},
        )
    )

    body = output["body"]
    assert body["value"] == "slot-list"
    assert body["status_text"] == "Path: 0.roi_id"


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


def test_payload_to_value_wraps_roi_list_items_for_for_each() -> None:
    """验证 Payload To Value 可把 roi-list.v1 转成 for-each 可迭代数组。"""

    output = _payload_to_value_handler(
        WorkflowNodeExecutionRequest(
            node_id="payload-to-value-rois",
            node_definition=object(),
            parameters={},
            input_values={
                "rois": {
                    "format_id": "amvision.roi-list.v1",
                    "items": [
                        {
                            "roi_id": "slot-loop",
                            "roi_kind": "bbox",
                            "bbox_xyxy": [0, 0, 10, 10],
                            "polygon_xy": [[0, 0], [10, 0], [10, 10], [0, 10]],
                            "area": 100,
                        }
                    ],
                    "count": 1,
                }
            },
            execution_metadata={},
        )
    )

    assert output["value"]["value"][0]["roi_id"] == "slot-loop"


def test_image_refs_to_value_list_and_value_to_image_ref_keep_refs_without_copying() -> None:
    """验证 image-refs 可转成 for-each 数组，并在循环体中恢复 image-ref。"""

    image_payload = {
        "transport_kind": "memory",
        "image_handle": "slot-image-01",
        "media_type": "image/bgr24",
        "width": 64,
        "height": 32,
    }
    list_output = _image_refs_to_value_list_handler(
        WorkflowNodeExecutionRequest(
            node_id="image-refs-to-value-list",
            node_definition=object(),
            parameters={},
            input_values={
                "images": {
                    "format_id": "amvision.image-refs.v1",
                    "items": [image_payload],
                    "count": 1,
                }
            },
            execution_metadata={},
        )
    )

    assert list_output["items"]["value"][0]["image_handle"] == "slot-image-01"
    assert list_output["summary"]["value"]["count"] == 1

    image_output = _value_to_image_ref_handler(
        WorkflowNodeExecutionRequest(
            node_id="value-to-image-ref",
            node_definition=object(),
            parameters={},
            input_values={"value": {"value": list_output["items"]["value"][0]}},
            execution_metadata={},
        )
    )

    assert image_output["image"]["transport_kind"] == "memory"
    assert image_output["image"]["image_handle"] == "slot-image-01"
    assert image_output["summary"]["value"]["media_type"] == "image/bgr24"


def test_classification_results_summary_counts_slot_states() -> None:
    """验证 classification 逐图结果可汇总为槽位状态和整盘状态。"""

    output = _classification_results_summary_handler(
        WorkflowNodeExecutionRequest(
            node_id="classification-results-summary",
            node_definition=object(),
            parameters={
                "expected_count": 3,
                "target_state": "empty",
                "empty_labels": ["slotempty"],
                "full_labels": ["slotfull"],
                "abnormal_labels": ["slotabnormal"],
                "min_score": 0.5,
                "include_items": True,
            },
            input_values={
                "results": {
                    "value": [
                        {"top_item": {"class_name": "slotempty", "probability": 0.91}},
                        {"top_item": {"class_name": "slotfull", "probability": 0.88}},
                        {"top_item": {"class_name": "slotabnormal", "probability": 0.31}},
                    ]
                }
            },
            execution_metadata={},
        )
    )

    summary = output["summary"]["value"]
    assert summary["count"] == 3
    assert summary["expected_count_matched"] is True
    assert summary["empty_count"] == 1
    assert summary["full_count"] == 1
    assert summary["abnormal_count"] == 0
    assert summary["unknown_count"] == 1
    assert summary["low_score_count"] == 1
    assert summary["all_empty"] is False
    assert summary["tray_state"] == "unknown"
    assert summary["state"] == "ng"
    assert summary["passed"] is False
    assert len(summary["problem_items"]) == 2
    assert output["passed"]["value"] is False
    assert output["all_empty"]["value"] is False
    assert output["has_abnormal"]["value"] is False
