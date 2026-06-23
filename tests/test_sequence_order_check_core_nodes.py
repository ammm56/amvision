"""sequence-order-check core 节点测试。"""

from __future__ import annotations

from backend.nodes.core_nodes.vision.pattern.sequence_order_check import _sequence_order_check_handler
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_sequence_order_check_passes_repeated_leftmost_selection() -> None:
    """验证 sequence-order-check 可按 leftmost 逐次取出同类目标并检查顺序。"""

    output = _sequence_order_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="sequence-order-check",
            node_definition=object(),
            parameters={
                "order_mode": "left-to-right",
                "ordered_items": [
                    {"item_name": "pin-1", "selector": {"class_name": "contact-pin", "strategy": "leftmost"}},
                    {"item_name": "pin-2", "selector": {"class_name": "contact-pin", "strategy": "leftmost"}},
                    {"item_name": "pin-3", "selector": {"class_name": "contact-pin", "strategy": "leftmost"}},
                ],
            },
            input_values={"regions": _build_regions_payload()},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is True
    metrics_value = output["metrics"]["value"]
    assert metrics_value["selected_region_ids"] == [
        "region-pin-left",
        "region-pin-middle",
        "region-pin-right",
    ]
    assert metrics_value["selected_item_names"] == ["pin-1", "pin-2", "pin-3"]


def test_sequence_order_check_rejects_wrong_class_sequence() -> None:
    """验证 sequence-order-check 会拒绝与实际排布不一致的顺序。"""

    output = _sequence_order_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="sequence-order-check",
            node_definition=object(),
            parameters={
                "order_mode": "left-to-right",
                "ordered_items": [
                    {"item_name": "cap", "selector": {"class_name": "cap", "strategy": "largest-area"}},
                    {"item_name": "nut", "selector": {"class_name": "nut", "strategy": "largest-area"}},
                    {"item_name": "washer", "selector": {"class_name": "washer", "strategy": "largest-area"}},
                ],
            },
            input_values={"regions": _build_regions_payload()},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is False
    metrics_value = output["metrics"]["value"]
    assert metrics_value["reason"] == "order-violation"
    assert metrics_value["violation_previous_item_name"] == "nut"
    assert metrics_value["violation_current_item_name"] == "washer"
    assert metrics_value["violation_actual_delta"] < 0


def _build_regions_payload() -> dict[str, object]:
    """构造三颗接触针与三个不同零件的测试 regions.v1 payload。"""

    return {
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "sequence-order-image",
            "media_type": "image/png",
            "width": 220,
            "height": 100,
        },
        "count": 6,
        "items": [
            {
                "region_id": "region-pin-left",
                "score": 0.97,
                "class_id": 1,
                "class_name": "contact-pin",
                "bbox_xyxy": [20.0, 20.0, 28.0, 28.0],
                "polygon_xy": [[20.0, 20.0], [28.0, 20.0], [28.0, 28.0], [20.0, 28.0]],
                "area": 64,
            },
            {
                "region_id": "region-pin-middle",
                "score": 0.96,
                "class_id": 1,
                "class_name": "contact-pin",
                "bbox_xyxy": [42.0, 20.0, 50.0, 28.0],
                "polygon_xy": [[42.0, 20.0], [50.0, 20.0], [50.0, 28.0], [42.0, 28.0]],
                "area": 64,
            },
            {
                "region_id": "region-pin-right",
                "score": 0.95,
                "class_id": 1,
                "class_name": "contact-pin",
                "bbox_xyxy": [64.0, 20.0, 72.0, 28.0],
                "polygon_xy": [[64.0, 20.0], [72.0, 20.0], [72.0, 28.0], [64.0, 28.0]],
                "area": 64,
            },
            {
                "region_id": "region-cap",
                "score": 0.94,
                "class_id": 2,
                "class_name": "cap",
                "bbox_xyxy": [100.0, 18.0, 114.0, 32.0],
                "polygon_xy": [[100.0, 18.0], [114.0, 18.0], [114.0, 32.0], [100.0, 32.0]],
                "area": 196,
            },
            {
                "region_id": "region-washer",
                "score": 0.93,
                "class_id": 3,
                "class_name": "washer",
                "bbox_xyxy": [122.0, 18.0, 136.0, 32.0],
                "polygon_xy": [[122.0, 18.0], [136.0, 18.0], [136.0, 32.0], [122.0, 32.0]],
                "area": 196,
            },
            {
                "region_id": "region-nut",
                "score": 0.92,
                "class_id": 4,
                "class_name": "nut",
                "bbox_xyxy": [144.0, 18.0, 158.0, 32.0],
                "polygon_xy": [[144.0, 18.0], [158.0, 18.0], [158.0, 32.0], [144.0, 32.0]],
                "area": 196,
            },
        ],
    }
