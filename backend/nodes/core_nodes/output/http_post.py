"""HTTP 结果回传节点。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.local_io import resolve_value_or_result_input
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.service import get_optional_dict_parameter
from backend.service.application.errors import InvalidRequestError, OperationTimeoutError, ServiceError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest

if TYPE_CHECKING:
    import httpx


def _http_post_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把结果对象或 value 内容回传到外部 HTTP 接口。"""

    payload_value, payload_kind = resolve_value_or_result_input(request)
    method = _read_method(request.parameters.get("method"))
    url = _read_url(request.parameters.get("url"))
    timeout_seconds = _read_timeout_seconds(request.parameters.get("timeout_seconds"))
    require_success = _read_require_success(request.parameters.get("require_success"))
    headers = _read_headers(request)

    import httpx

    try:
        response = _send_http_request(
            method=method,
            url=url,
            json=payload_value,
            headers=headers,
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise OperationTimeoutError(
            "HTTP 回传超时",
            details={"node_id": request.node_id, "url": url, "timeout_seconds": timeout_seconds},
        ) from exc
    except httpx.HTTPError as exc:
        raise ServiceError(
            "HTTP 回传失败",
            code="http_post_failed",
            status_code=502,
            details={"node_id": request.node_id, "url": url, "error_message": str(exc)},
        ) from exc

    response_payload = _build_response_payload(
        response=response,
        url=url,
        method=method,
        payload_kind=payload_kind,
    )
    if require_success and not response.is_success:
        raise ServiceError(
            "HTTP 回传返回非成功状态码",
            code="http_post_unsuccessful_status",
            status_code=502,
            details={
                "node_id": request.node_id,
                "url": url,
                "method": method,
                "status_code": response.status_code,
                "payload_kind": payload_kind,
            },
        )
    return {"response": build_value_payload(response_payload)}


def _send_http_request(**kwargs: object) -> httpx.Response:
    """执行 HTTP 请求；保持 httpx 在节点运行时按需导入。"""

    import httpx

    return httpx.request(**kwargs)


def _build_response_payload(
    *,
    response: httpx.Response,
    url: str,
    method: str,
    payload_kind: str,
) -> dict[str, object]:
    """构造 HTTP 回传结果摘要。"""

    payload: dict[str, object] = {
        "ok": response.is_success,
        "status_code": response.status_code,
        "url": url,
        "method": method,
        "payload_kind": payload_kind,
        "headers": {str(key): value for key, value in response.headers.items()},
    }
    response_json = _try_read_response_json(response)
    if response_json is not None:
        payload["body_json"] = response_json
    else:
        payload["body_text"] = response.text
    return payload


def _try_read_response_json(response: httpx.Response) -> object | None:
    """尝试从响应中读取 JSON。"""

    content_type = response.headers.get("content-type", "").lower()
    if "json" not in content_type:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _read_method(raw_value: object) -> str:
    """读取 HTTP 方法。"""

    if raw_value is None:
        return "POST"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("http-post 的 method 必须是字符串")
    normalized_value = raw_value.strip().upper()
    if normalized_value not in {"POST", "PUT", "PATCH"}:
        raise InvalidRequestError(
            "http-post 当前仅支持 POST / PUT / PATCH",
            details={"method": raw_value},
        )
    return normalized_value


def _read_url(raw_value: object) -> str:
    """读取目标 URL。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("http-post 的 url 必须是非空字符串")
    return raw_value.strip()


def _read_timeout_seconds(raw_value: object) -> float:
    """读取超时参数。"""

    if raw_value is None:
        return 5.0
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError("http-post 的 timeout_seconds 必须是数字")
    normalized_value = float(raw_value)
    if normalized_value <= 0:
        raise InvalidRequestError("http-post 的 timeout_seconds 必须大于 0")
    return normalized_value


def _read_require_success(raw_value: object) -> bool:
    """读取非 2xx 是否视为失败。"""

    if raw_value is None:
        return True
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("http-post 的 require_success 必须是布尔值")
    return raw_value


def _read_headers(request: WorkflowNodeExecutionRequest) -> dict[str, str]:
    """读取并规范化请求头。"""

    headers = get_optional_dict_parameter(request, "headers")
    normalized_headers: dict[str, str] = {}
    for key, value in headers.items():
        if not isinstance(value, (str, int, float, bool)):
            raise InvalidRequestError(
                "http-post 的 headers 值必须可转换为字符串",
                details={"header_name": key},
            )
        normalized_headers[str(key)] = str(value)
    if "Content-Type" not in normalized_headers and "content-type" not in normalized_headers:
        normalized_headers["Content-Type"] = "application/json"
    return normalized_headers


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.http-post",
        display_name="HTTP Post",
        category="integration.output",
        description="把 result-record 或 value 内容回传到外部 HTTP 接口，适合 MES、上位机和现场回调。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="result-record.v1",
                required=False,
            ),
            NodePortDefinition(
                name="alarm",
                display_name="Alarm",
                payload_type_id="alarm-record.v1",
                required=False,
            ),
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="response",
                display_name="Response",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "title": "目标 URL"},
                "method": {
                    "type": "string",
                    "title": "HTTP 方法",
                    "enum": ["POST", "PUT", "PATCH"],
                    "default": "POST",
                },
                "timeout_seconds": {
                    "type": "number",
                    "title": "超时秒数",
                    "default": 5.0,
                    "exclusiveMinimum": 0,
                },
                "require_success": {
                    "type": "boolean",
                    "title": "非 2xx 视为失败",
                    "default": True,
                },
                "headers": {
                    "type": "object",
                    "title": "请求头",
                    "additionalProperties": {
                        "type": ["string", "number", "boolean"],
                    },
                },
            },
            "required": ["url"],
        },
        capability_tags=("integration.output", "http.post", "inspection.result.callback"),
    ),
    handler=_http_post_handler,
)
