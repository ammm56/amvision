"""MES HTTP 输出节点输入来源读取。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import (
    build_value_payload,
    require_value_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.output_mes_http_nodes.backend.runtime.types import SourceKind


def _read_source_roots(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> tuple[str, dict[SourceKind, dict[str, object] | None]]:
    """读取并校验主业务输入与 request 上下文。"""

    result_payload = _read_optional_inline_object_input(
        request=request,
        input_name="result",
        node_name=node_name,
    )
    workflow_result_payload = _read_optional_inline_object_input(
        request=request,
        input_name="workflow_result",
        node_name=node_name,
    )
    summary_payload = _read_optional_value_object_input(
        request=request,
        input_name="summary",
        node_name=node_name,
    )
    request_payload = _read_optional_value_object_input(
        request=request,
        input_name="request",
        node_name=node_name,
    )
    primary_sources = tuple(
        (source_kind, source_value)
        for source_kind, source_value in (
            ("result", result_payload),
            ("workflow_result", workflow_result_payload),
            ("summary", summary_payload),
        )
        if source_value is not None
    )
    if not primary_sources:
        raise InvalidRequestError(
            f"{node_name} 缺少主业务输入，必须提供 result / workflow_result / summary 之一"
        )
    if len(primary_sources) > 1:
        raise InvalidRequestError(
            f"{node_name} 的 result / workflow_result / summary 只能同时提供一个",
            details={
                "provided_sources": [source_kind for source_kind, _ in primary_sources]
            },
        )
    primary_source_kind = primary_sources[0][0]
    source_roots: dict[SourceKind, dict[str, object] | None] = {
        "result": result_payload,
        "workflow_result": workflow_result_payload,
        "summary": summary_payload,
        "request": request_payload,
        "literal": None,
    }
    return primary_source_kind, source_roots


def _read_optional_inline_object_input(
    *,
    request: WorkflowNodeExecutionRequest,
    input_name: str,
    node_name: str,
) -> dict[str, object] | None:
    """读取可选 inline-json 对象输入。"""

    raw_payload = request.input_values.get(input_name)
    if raw_payload is None:
        return None
    normalized_value = build_value_payload(raw_payload)["value"]
    if not isinstance(normalized_value, dict):
        raise InvalidRequestError(f"{node_name} 的输入 {input_name} 必须是对象 payload")
    return normalized_value


def _read_optional_value_object_input(
    *,
    request: WorkflowNodeExecutionRequest,
    input_name: str,
    node_name: str,
) -> dict[str, object] | None:
    """读取可选 value.v1 对象输入。"""

    raw_payload = request.input_values.get(input_name)
    if raw_payload is None:
        return None
    object_value = require_value_payload(raw_payload, field_name=input_name)["value"]
    if not isinstance(object_value, dict):
        raise InvalidRequestError(
            f"{node_name} 的输入 {input_name} 必须是对象 value payload"
        )
    return object_value
