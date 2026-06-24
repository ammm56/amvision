"""MES HTTP 输出节点请求头与鉴权参数。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes.output_mes_http_nodes.backend.runtime.parameters import (
    _read_required_non_empty_string,
)
from custom_nodes.output_mes_http_nodes.backend.runtime.types import AuthKind

_REDACTED_HEADER_VALUE = "***REDACTED***"


def _read_headers(
    *,
    raw_value: object,
    auth_kind: AuthKind,
    auth_token: object,
    auth_header_name: object,
    node_name: str,
) -> dict[str, str]:
    """读取并规范化请求头。"""

    headers: dict[str, str] = {}
    if raw_value is not None:
        normalized_value = build_value_payload(raw_value)["value"]
        if not isinstance(normalized_value, dict):
            raise InvalidRequestError(f"{node_name} 的 headers 必须是对象")
        for key, value in normalized_value.items():
            if not isinstance(value, (str, int, float, bool)):
                raise InvalidRequestError(
                    f"{node_name} 的 headers 值必须可转换为字符串",
                    details={"header_name": key},
                )
            headers[str(key)] = _stringify_header_value(value)

    if auth_kind == "none":
        if auth_token is not None or auth_header_name is not None:
            raise InvalidRequestError(
                f"{node_name} 的 auth_kind=none 时不能同时提供 auth_token 或 auth_header_name"
            )
    elif auth_kind == "bearer_token":
        token = _read_required_non_empty_string(
            raw_value=auth_token,
            node_name=node_name,
            field_name="auth_token",
        )
        if auth_header_name is not None:
            raise InvalidRequestError(
                f"{node_name} 的 bearer_token 模式不支持 auth_header_name"
            )
        headers["Authorization"] = f"Bearer {token}"
    else:
        token = _read_required_non_empty_string(
            raw_value=auth_token,
            node_name=node_name,
            field_name="auth_token",
        )
        header_name = _read_required_non_empty_string(
            raw_value=auth_header_name,
            node_name=node_name,
            field_name="auth_header_name",
        )
        headers[header_name] = token

    if "Content-Type" not in headers and "content-type" not in headers:
        headers["Content-Type"] = "application/json"
    return headers


def _sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    """脱敏 prepared_request 中的敏感请求头。"""

    sanitized_headers: dict[str, str] = {}
    for key, value in headers.items():
        normalized_key = key.strip().lower()
        if any(
            token in normalized_key
            for token in ("authorization", "token", "secret", "password", "api-key")
        ):
            sanitized_headers[key] = _REDACTED_HEADER_VALUE
            continue
        sanitized_headers[key] = value
    return sanitized_headers


def _stringify_header_value(value: object) -> str:
    """把 header 值规范化为字符串。"""

    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
