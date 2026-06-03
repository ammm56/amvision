"""工业规则节点轻量回归测试。"""

from __future__ import annotations

from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from backend.nodes.core_nodes.ok_ng_decision import _ok_ng_decision_handler
from backend.nodes.core_nodes.presence_check import _presence_check_handler
from backend.nodes.core_nodes.result_record import _result_record_handler
from backend.nodes.core_nodes.threshold_check import _threshold_check_handler
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_core_catalog_contains_result_record_payload_contract() -> None:
    """验证 core catalog 已公开 result-record.v1 contract。"""

    payload_type_ids = {contract.payload_type_id for contract in get_core_workflow_payload_contracts()}

    assert "result-record.v1" in payload_type_ids


def test_threshold_check_handler_compares_numeric_value() -> None:
    """验证阈值判断节点会输出布尔结果和指标摘要。"""

    output = _threshold_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="threshold-check",
            node_definition=object(),
            parameters={"operator": ">=", "threshold": 0.75},
            input_values={"value": {"value": 0.82}},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is True
    assert output["metrics"]["value"]["threshold"] == 0.75
    assert output["metrics"]["value"]["value"] == 0.82


def test_presence_check_handler_uses_regions_count() -> None:
    """验证存在性判断节点可直接基于 regions.v1 数量判断。"""

    output = _presence_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="presence-check",
            node_definition=object(),
            parameters={"min_count": 1, "max_count": 2},
            input_values={
                "regions": {
                    "count": 2,
                    "items": [
                        {
                            "region_id": "r1",
                            "score": 0.9,
                            "class_id": 1,
                            "class_name": "defect-a",
                            "bbox_xyxy": [0.0, 0.0, 4.0, 4.0],
                            "polygon_xy": [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]],
                            "area": 16,
                        },
                        {
                            "region_id": "r2",
                            "score": 0.8,
                            "class_id": 2,
                            "class_name": "defect-b",
                            "bbox_xyxy": [5.0, 0.0, 9.0, 4.0],
                            "polygon_xy": [[5.0, 0.0], [9.0, 0.0], [9.0, 4.0], [5.0, 4.0]],
                            "area": 16,
                        },
                    ],
                }
            },
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is True
    assert output["metrics"]["value"]["count"] == 2
    assert output["metrics"]["value"]["source_kind"] == "regions"


def test_ok_ng_decision_handler_aggregates_multiple_conditions() -> None:
    """验证 OK/NG 节点会把多路布尔条件收成最终判定。"""

    output = _ok_ng_decision_handler(
        WorkflowNodeExecutionRequest(
            node_id="ok-ng-decision",
            node_definition=object(),
            parameters={"mode": "all"},
            input_values={"conditions": ({"value": True}, {"value": False}, {"value": True})},
            execution_metadata={},
        )
    )

    assert output["decision"]["value"] == "NG"
    assert output["ok"]["value"] is False
    assert output["summary"]["value"]["failed_indexes"] == [2]


def test_result_record_handler_builds_result_payload() -> None:
    """验证结果对象节点会输出统一 result-record.v1。"""

    output = _result_record_handler(
        WorkflowNodeExecutionRequest(
            node_id="result-record",
            node_definition=object(),
            parameters={},
            input_values={
                "decision": {"value": "OK"},
                "metrics": {"value": {"area_ratio": 0.18}},
                "conditions": {"value": [{"name": "coverage", "passed": True}]},
                "reason": {"value": "coverage pass"},
                "metadata": {"value": {"station_id": "line-a-01"}},
                "image": {
                    "transport_kind": "memory",
                    "image_handle": "image-a",
                    "media_type": "image/png",
                    "width": 64,
                    "height": 64,
                },
            },
            execution_metadata={},
        )
    )

    result_payload = output["result"]
    assert result_payload["ok_ng"] == "OK"
    assert result_payload["ok"] is True
    assert result_payload["metrics"]["area_ratio"] == 0.18
    assert result_payload["metadata"]["station_id"] == "line-a-01"
    assert result_payload["image"]["transport_kind"] == "memory"
