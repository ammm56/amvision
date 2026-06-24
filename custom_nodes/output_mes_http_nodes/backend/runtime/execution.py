"""MES HTTP 输出节点执行入口。"""

from __future__ import annotations

import httpx

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import OperationTimeoutError, ServiceError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.output_mes_http_nodes.backend.runtime.http_client import (
    _build_response_payload,
)
from custom_nodes.output_mes_http_nodes.backend.runtime.parameters import (
    _read_auth_kind,
    _read_body_mode,
    _read_method,
    _read_on_missing_policy,
    _read_optional_object_parameter,
    _read_require_success,
    _read_timeout_seconds,
    _read_url,
)
from custom_nodes.output_mes_http_nodes.backend.runtime.payloads import (
    _build_body_payload,
    _build_query_payload,
    _read_field_mappings,
    _read_query_mappings,
    _read_source_roots,
)
from custom_nodes.output_mes_http_nodes.backend.runtime.request import (
    _read_headers,
    _sanitize_headers,
)


def execute_mes_http_post_node(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> dict[str, object]:
    """执行第一阶段受限 MES HTTP 输出。"""

    primary_source_kind, source_roots = _read_source_roots(
        request=request,
        node_name=node_name,
    )
    method = _read_method(
        raw_value=request.parameters.get("method"),
        node_name=node_name,
    )
    url = _read_url(
        raw_value=request.parameters.get("url"),
        node_name=node_name,
    )
    timeout_seconds = _read_timeout_seconds(
        raw_value=request.parameters.get("timeout_seconds"),
        node_name=node_name,
    )
    require_success = _read_require_success(
        raw_value=request.parameters.get("require_success"),
        node_name=node_name,
    )
    auth_kind = _read_auth_kind(
        raw_value=request.parameters.get("auth_kind"),
        node_name=node_name,
    )
    headers = _read_headers(
        raw_value=request.parameters.get("headers"),
        auth_kind=auth_kind,
        auth_token=request.parameters.get("auth_token"),
        auth_header_name=request.parameters.get("auth_header_name"),
        node_name=node_name,
    )
    body_mode = _read_body_mode(
        raw_value=request.parameters.get("body_mode"),
        node_name=node_name,
    )
    default_on_missing = _read_on_missing_policy(
        raw_value=request.parameters.get("on_missing"),
        node_name=node_name,
        field_name="on_missing",
        default_value="error",
    )
    query_template = _read_optional_object_parameter(
        raw_value=request.parameters.get("query_template"),
        node_name=node_name,
        field_name="query_template",
    )
    query_mappings = _read_query_mappings(
        raw_value=request.parameters.get("query_mappings"),
        node_name=node_name,
    )
    body_template = _read_optional_object_parameter(
        raw_value=request.parameters.get("body_template"),
        node_name=node_name,
        field_name="body_template",
    )
    static_fields = _read_optional_object_parameter(
        raw_value=request.parameters.get("static_fields"),
        node_name=node_name,
        field_name="static_fields",
    )
    field_mappings = _read_field_mappings(
        raw_value=request.parameters.get("field_mappings"),
        node_name=node_name,
    )

    query_payload = _build_query_payload(
        template=query_template,
        mappings=query_mappings,
        source_roots=source_roots,
        default_on_missing=default_on_missing,
        node_name=node_name,
    )
    body_payload = _build_body_payload(
        body_template=body_template,
        static_fields=static_fields,
        mappings=field_mappings,
        source_roots=source_roots,
        default_on_missing=default_on_missing,
        node_name=node_name,
    )
    prepared_request_payload = build_value_payload(
        {
            "primary_source_kind": primary_source_kind,
            "url": url,
            "method": method,
            "body_mode": body_mode,
            "auth_kind": auth_kind,
            "query": query_payload,
            "headers": _sanitize_headers(headers),
            "body": body_payload,
            "has_request_context": source_roots["request"] is not None,
            "field_mapping_count": len(field_mappings),
            "query_mapping_count": len(query_mappings),
        }
    )

    try:
        response = httpx.request(
            method=method,
            url=url,
            params=query_payload or None,
            json=body_payload,
            headers=headers,
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise OperationTimeoutError(
            "MES HTTP 回传超时",
            details={
                "node_id": request.node_id,
                "url": url,
                "timeout_seconds": timeout_seconds,
            },
        ) from exc
    except httpx.HTTPError as exc:
        raise ServiceError(
            "MES HTTP 回传失败",
            code="mes_http_post_failed",
            status_code=502,
            details={"node_id": request.node_id, "url": url, "error_message": str(exc)},
        ) from exc

    response_payload = _build_response_payload(
        response=response,
        url=url,
        method=method,
        primary_source_kind=primary_source_kind,
    )
    if require_success and not response.is_success:
        raise ServiceError(
            "MES HTTP 回传返回非成功状态码",
            code="mes_http_post_unsuccessful_status",
            status_code=502,
            details={
                "node_id": request.node_id,
                "url": url,
                "method": method,
                "status_code": response.status_code,
                "primary_source_kind": primary_source_kind,
            },
        )
    return {
        "response": build_value_payload(response_payload),
        "prepared_request": prepared_request_payload,
    }
