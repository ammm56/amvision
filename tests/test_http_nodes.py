"""HTTP Request 输出节点行为测试。"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.http_nodes.categories.request.backend.nodes import http_request
import custom_nodes.http_nodes.categories.request.backend.runtime.execution as http_runtime


def test_http_request_builds_request_from_result_and_request_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 HTTP Request 会按受限映射规则组装请求。"""

    captured_request: dict[str, object] = {}

    def _fake_request(**kwargs: object) -> httpx.Response:
        captured_request.update(kwargs)
        request = httpx.Request(method=str(kwargs["method"]), url=str(kwargs["url"]))
        return httpx.Response(
            status_code=202,
            headers={"content-type": "application/json"},
            json={"accepted": True},
            request=request,
        )

    monkeypatch.setattr(http_runtime.httpx, "request", _fake_request)

    output = http_request.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="http-request-node",
            node_definition=SimpleNamespace(node_type_id=http_request.NODE_TYPE_ID),
            parameters={
                "url": "https://mes.example.test/api/inspection-result",
                "method": "PUT",
                "timeout_seconds": 12.5,
                "headers": {"X-Site": "line-a-01"},
                "auth_kind": "bearer_token",
                "auth_token": "super-secret-token",
                "query_template": {"source": "amvision"},
                "query_mappings": [
                    {
                        "target_name": "work_order_id",
                        "source_kind": "request",
                        "source_path": "work_order_id",
                    }
                ],
                "body_mode": "json_envelope",
                "body_template": {"site": "", "payload": {}},
                "static_fields": {"site": "station-a", "payload": {"schema": "v1"}},
                "field_mappings": [
                    {
                        "target_path": "payload.ok_ng",
                        "source_kind": "result",
                        "source_path": "ok_ng",
                    },
                    {
                        "target_path": "payload.coverage_ratio",
                        "source_kind": "result",
                        "source_path": "metrics.coverage_ratio",
                    },
                    {
                        "target_path": "payload.work_order_id",
                        "source_kind": "request",
                        "source_path": "work_order_id",
                    },
                    {
                        "target_path": "payload.result_code",
                        "source_kind": "literal",
                        "literal_value": 2001,
                    },
                ],
            },
            input_values={
                "result": {
                    "ok_ng": "NG",
                    "ok": False,
                    "metrics": {"coverage_ratio": 0.73},
                    "metadata": {"part_id": "part-001"},
                },
                "request": {"value": {"work_order_id": "WO-1001"}},
            },
            execution_metadata={},
        )
    )

    assert captured_request["method"] == "PUT"
    assert captured_request["url"] == "https://mes.example.test/api/inspection-result"
    assert captured_request["timeout"] == 12.5
    assert captured_request["params"] == {
        "source": "amvision",
        "work_order_id": "WO-1001",
    }
    assert captured_request["json"] == {
        "site": "station-a",
        "payload": {
            "schema": "v1",
            "ok_ng": "NG",
            "coverage_ratio": 0.73,
            "work_order_id": "WO-1001",
            "result_code": 2001,
        },
    }
    assert captured_request["headers"]["Authorization"] == "Bearer super-secret-token"
    assert captured_request["headers"]["Content-Type"] == "application/json"
    assert (
        output["prepared_request"]["value"]["headers"]["Authorization"]
        == "***REDACTED***"
    )
    assert output["prepared_request"]["value"]["body_mode"] == "json_envelope"
    assert output["response"]["value"]["ok"] is True
    assert output["response"]["value"]["status_code"] == 202
    assert output["response"]["value"]["primary_source_kind"] == "result"


def test_http_request_rejects_multiple_primary_inputs() -> None:
    """验证 http-request 会拒绝同时提供多个主业务输入。"""

    with pytest.raises(InvalidRequestError, match="只能同时提供一个"):
        http_request.handle_node(
            WorkflowNodeExecutionRequest(
                node_id="http-request-invalid",
                node_definition=SimpleNamespace(
                    node_type_id=http_request.NODE_TYPE_ID
                ),
                parameters={"url": "https://mes.example.test/api/inspection-result"},
                input_values={
                    "result": {"ok_ng": "OK", "ok": True},
                    "workflow_result": {
                        "status": "succeeded",
                        "code": 0,
                        "message": "ok",
                    },
                },
                execution_metadata={},
            )
        )


def test_http_request_sends_value_input_as_default_json_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证未配置映射时直接把通用 value 对象作为 JSON body 发送。"""

    captured_request: dict[str, object] = {}

    def _fake_request(**kwargs: object) -> httpx.Response:
        captured_request.update(kwargs)
        request = httpx.Request(method=str(kwargs["method"]), url=str(kwargs["url"]))
        return httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            json={"accepted": True},
            request=request,
        )

    monkeypatch.setattr(http_runtime.httpx, "request", _fake_request)

    output = http_request.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="http-request-value",
            node_definition=SimpleNamespace(node_type_id=http_request.NODE_TYPE_ID),
            parameters={"url": "https://api.example.test/results"},
            input_values={
                "value": {
                    "value": {
                        "status": "succeeded",
                        "result_id": "result-001",
                    }
                }
            },
            execution_metadata={},
        )
    )

    assert captured_request["json"] == {
        "status": "succeeded",
        "result_id": "result-001",
    }
    assert output["prepared_request"]["value"]["primary_source_kind"] == "value"


def test_http_request_supports_skip_and_null_mapping_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 http-request 支持 skip/null 缺失策略。"""

    captured_request: dict[str, object] = {}

    def _fake_request(**kwargs: object) -> httpx.Response:
        captured_request.update(kwargs)
        request = httpx.Request(method=str(kwargs["method"]), url=str(kwargs["url"]))
        return httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            json={"ok": True},
            request=request,
        )

    monkeypatch.setattr(http_runtime.httpx, "request", _fake_request)

    output = http_request.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="http-request-summary",
            node_definition=SimpleNamespace(node_type_id=http_request.NODE_TYPE_ID),
            parameters={
                "url": "https://mes.example.test/api/batch-summary",
                "query_mappings": [
                    {
                        "target_name": "station_id",
                        "source_kind": "request",
                        "source_path": "station_id",
                        "on_missing": "skip",
                    }
                ],
                "field_mappings": [
                    {
                        "target_path": "payload.pass_ratio",
                        "source_kind": "summary",
                        "source_path": "pass_ratio",
                    },
                    {
                        "target_path": "payload.operator_id",
                        "source_kind": "request",
                        "source_path": "operator_id",
                        "on_missing": "null",
                    },
                ],
            },
            input_values={
                "summary": {
                    "value": {
                        "ok_count": 9,
                        "ng_count": 1,
                        "pass_ratio": 0.9,
                    }
                }
            },
            execution_metadata={},
        )
    )

    assert captured_request["params"] is None
    assert captured_request["json"] == {
        "payload": {"pass_ratio": 0.9, "operator_id": None}
    }
    assert output["prepared_request"]["value"]["query"] == {}
    assert output["response"]["value"]["body_json"]["ok"] is True
