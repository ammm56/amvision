"""工业规则节点轻量回归测试。"""

from __future__ import annotations

from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from backend.nodes.core_nodes.alarm_condition import _alarm_condition_handler
from backend.nodes.core_nodes.alarm_record import _alarm_record_handler
from backend.nodes.core_nodes.ok_ng_decision import _ok_ng_decision_handler
from backend.nodes.core_nodes.presence_check import _presence_check_handler
from backend.nodes.core_nodes.process_decision import _process_decision_handler
from backend.nodes.core_nodes.range_check import _range_check_handler
from backend.nodes.core_nodes.result_record import _result_record_handler
from backend.nodes.core_nodes.threshold_check import _threshold_check_handler
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_core_catalog_contains_result_record_payload_contract() -> None:
    """验证 core catalog 已公开 result-record.v1 contract。"""

    payload_type_ids = {contract.payload_type_id for contract in get_core_workflow_payload_contracts()}

    assert "result-record.v1" in payload_type_ids
    assert "alarm-record.v1" in payload_type_ids


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
                "alarm": {
                    "active": False,
                    "level": "info",
                    "message": "inspection normal",
                },
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
    assert result_payload["alarm"]["active"] is False
    assert result_payload["image"]["transport_kind"] == "memory"


def test_range_check_handler_validates_numeric_range() -> None:
    """验证范围判断节点会输出布尔结果和范围指标。"""

    output = _range_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="range-check",
            node_definition=object(),
            parameters={"min_value": 0.2, "max_value": 0.5},
            input_values={"value": {"value": 0.33}},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is True
    assert output["metrics"]["value"]["min_value"] == 0.2
    assert output["metrics"]["value"]["max_value"] == 0.5


def test_alarm_record_handler_builds_alarm_payload() -> None:
    """验证报警对象节点会输出统一 alarm-record.v1。"""

    output = _alarm_record_handler(
        WorkflowNodeExecutionRequest(
            node_id="alarm-record",
            node_definition=object(),
            parameters={"alarm_level": "critical", "alarm_code": "GLUE-LOW"},
            input_values={
                "active": {"value": True},
                "message": {"value": "coverage below threshold"},
                "metrics": {"value": {"coverage_ratio": 0.12}},
            },
            execution_metadata={},
        )
    )

    alarm_payload = output["alarm"]
    assert alarm_payload["active"] is True
    assert alarm_payload["level"] == "critical"
    assert alarm_payload["code"] == "GLUE-LOW"
    assert alarm_payload["message"] == "coverage below threshold"
    assert alarm_payload["metrics"]["coverage_ratio"] == 0.12


def test_alarm_condition_handler_builds_alarm_from_failed_rule() -> None:
    """验证报警条件节点可把规则失败直接收成报警对象。"""

    output = _alarm_condition_handler(
        WorkflowNodeExecutionRequest(
            node_id="alarm-condition",
            node_definition=object(),
            parameters={
                "trigger_when": "condition-false",
                "alarm_level": "error",
                "alarm_code": "COVERAGE-LOW",
                "alarm_message": "coverage below threshold",
                "clear_message": "coverage restored",
            },
            input_values={
                "condition": {"value": False},
                "metrics": {"value": {"coverage_ratio": 0.12}},
            },
            execution_metadata={},
        )
    )

    assert output["active"]["value"] is True
    assert output["alarm"]["active"] is True
    assert output["alarm"]["level"] == "error"
    assert output["alarm"]["code"] == "COVERAGE-LOW"
    assert output["alarm"]["message"] == "coverage below threshold"


def test_process_decision_handler_builds_result_record_from_conditions() -> None:
    """验证工艺判定节点可直接把多路条件收成结果对象。"""

    output = _process_decision_handler(
        WorkflowNodeExecutionRequest(
            node_id="process-decision",
            node_definition=object(),
            parameters={
                "mode": "all",
                "condition_names": ["coverage", "continuity"],
                "ng_reason": "continuity failed",
            },
            input_values={
                "conditions": ({"value": True}, {"value": False}),
                "metrics": {"value": {"coverage_ratio": 0.91, "continuity_score": 0.42}},
                "alarm": {
                    "active": True,
                    "level": "warning",
                    "message": "continuity below target",
                    "code": "CONT-LOW",
                },
            },
            execution_metadata={},
        )
    )

    result_payload = output["result"]
    assert output["decision"]["value"] == "NG"
    assert output["ok"]["value"] is False
    assert result_payload["ok_ng"] == "NG"
    assert result_payload["reason"] == "continuity failed"
    assert result_payload["conditions"][0]["name"] == "coverage"
    assert result_payload["conditions"][1]["passed"] is False
    assert result_payload["alarm"]["code"] == "CONT-LOW"
    assert output["summary"]["value"]["failed_condition_names"] == ["continuity"]
