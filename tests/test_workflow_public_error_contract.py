"""Workflow 公开错误对象的稳定性与脱敏测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.contracts.errors import ErrorContract
from backend.service.application.public_errors import (
    build_error_contract,
    build_workflow_error_contract,
    without_public_error_metadata,
)
from backend.service.api.rest.v1.routes.workflow_runtime_support.responses import (
    build_workflow_run_event_contract,
)
from backend.service.domain.workflows.workflow_runtime_records import WorkflowRunEvent


def test_error_contract_requires_complete_fixed_shape() -> None:
    """错误对象必须包含三个字段，且拒绝空文本和额外字段。"""

    contract = ErrorContract(code="invalid_request", message="请求无效", details={})
    assert contract.model_dump(mode="json") == {
        "code": "invalid_request",
        "message": "请求无效",
        "details": {},
    }

    with pytest.raises(ValidationError):
        ErrorContract.model_validate({"code": "invalid_request", "message": "请求无效"})
    with pytest.raises(ValidationError):
        ErrorContract.model_validate(
            {
                "code": "invalid_request",
                "message": "请求无效",
                "details": {},
                "extra": True,
            }
        )
    with pytest.raises(ValidationError):
        ErrorContract(code=" ", message="请求无效", details={})
    with pytest.raises(ValidationError):
        ErrorContract(code="invalid_request", message=" ", details={})


def test_public_error_details_remove_internal_diagnostics_and_binary_content() -> None:
    """公开 details 不得泄漏内部错误字段、路径或二进制内容。"""

    marker = "private-input-marker"
    contract = build_error_contract(
        code="invalid_request",
        message="请求无效",
        details={
            "binding_id": "request_json",
            "error_message": marker,
            "traceback": marker,
            "nested": {"error_type": "ValueError", "safe_count": 2},
            "content": marker.encode(),
            "path": Path("C:/secret/input.json"),
        },
    )

    payload = contract.model_dump(mode="json")
    assert marker not in str(payload)
    assert payload["details"] == {
        "binding_id": "request_json",
        "nested": {"safe_count": 2},
        "content": {"kind": "bytes", "size_bytes": len(marker)},
        "path": "<path>",
    }


@pytest.mark.parametrize(
    ("state", "expected_code"),
    [
        ("failed", "workflow_execution_failed"),
        ("timed_out", "operation_timeout"),
        ("cancelled", "operation_cancelled"),
    ],
)
def test_workflow_error_mapping_supplies_stable_defaults(
    state: str,
    expected_code: str,
) -> None:
    """内部记录不完整时按终态补齐稳定公开错误码。"""

    contract = build_workflow_error_contract(
        state=state,
        error_message=None,
        error_details=None,
    )

    assert contract is not None
    assert contract.code == expected_code
    assert contract.message
    assert contract.details == {}


def test_workflow_error_mapping_uses_internal_code_without_parallel_fields() -> None:
    """内部稳定错误码只进入 error.code，不在 details 或 metadata 重复。"""

    contract = build_workflow_error_contract(
        state="failed",
        error_message="输入不符合公开 schema",
        error_details={
            "error_code": "workflow_input_payload_schema_invalid",
            "error_message": "duplicate",
            "binding_id": "request_json",
        },
    )

    assert contract is not None
    assert contract.model_dump(mode="json") == {
        "code": "workflow_input_payload_schema_invalid",
        "message": "输入不符合公开 schema",
        "details": {"binding_id": "request_json"},
    }
    assert without_public_error_metadata(
        {
            "workflow_runtime_id": "workflow-runtime-1",
            "error_code": "legacy",
            "error_details": {"legacy": True},
        }
    ) == {"workflow_runtime_id": "workflow-runtime-1"}


def test_non_error_workflow_state_never_exposes_error() -> None:
    """成功和进行中状态固定返回 error=null。"""

    assert (
        build_workflow_error_contract(
            state="succeeded",
            error_message="stale internal value",
            error_details={"error_code": "stale"},
        )
        is None
    )


def test_workflow_event_converts_legacy_internal_error_fields_once() -> None:
    """REST 与 WebSocket 共用的事件构造器只输出统一 error。"""

    event = WorkflowRunEvent(
        workflow_run_id="workflow-run-1",
        workflow_runtime_id="workflow-runtime-1",
        sequence=1,
        event_type="run.failed",
        created_at="2026-09-07T00:00:00Z",
        message="failed",
        payload={
            "state": "failed",
            "error_message": "节点执行失败",
            "error_details": {
                "error_code": "node_execution_failed",
                "node_id": "node-1",
                "error_type": "ValueError",
            },
        },
    )

    payload = build_workflow_run_event_contract(event).model_dump(mode="json")[
        "payload"
    ]
    assert payload == {
        "state": "failed",
        "error": {
            "code": "node_execution_failed",
            "message": "节点执行失败",
            "details": {"node_id": "node-1"},
        },
    }
