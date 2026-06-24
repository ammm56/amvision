"""MES HTTP 输出节点参数读取。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes.output_mes_http_nodes.backend.runtime.types import (
    AuthKind,
    BodyMode,
    HttpMethod,
    OnMissingPolicy,
)


def _read_method(*, raw_value: object, node_name: str) -> HttpMethod:
    """读取 HTTP 方法。"""

    if raw_value is None:
        return "POST"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 method 必须是字符串")
    normalized_value = raw_value.strip().upper()
    if normalized_value not in {"POST", "PUT"}:
        raise InvalidRequestError(
            f"{node_name} 当前仅支持 POST / PUT",
            details={"method": raw_value},
        )
    return normalized_value  # type: ignore[return-value]


def _read_url(*, raw_value: object, node_name: str) -> str:
    """读取目标 URL。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{node_name} 的 url 必须是非空字符串")
    return raw_value.strip()


def _read_timeout_seconds(*, raw_value: object, node_name: str) -> float:
    """读取请求超时。"""

    if raw_value is None:
        return 5.0
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{node_name} 的 timeout_seconds 必须是数字")
    normalized_value = float(raw_value)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{node_name} 的 timeout_seconds 必须大于 0")
    return normalized_value


def _read_require_success(*, raw_value: object, node_name: str) -> bool:
    """读取非 2xx 是否视为失败。"""

    if raw_value is None:
        return True
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{node_name} 的 require_success 必须是布尔值")
    return raw_value


def _read_auth_kind(*, raw_value: object, node_name: str) -> AuthKind:
    """读取鉴权模式。"""

    if raw_value is None:
        return "none"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 auth_kind 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"none", "bearer_token", "header_static"}:
        raise InvalidRequestError(
            f"{node_name} 的 auth_kind 不支持当前取值",
            details={"auth_kind": raw_value},
        )
    return normalized_value  # type: ignore[return-value]


def _read_body_mode(*, raw_value: object, node_name: str) -> BodyMode:
    """读取 body 组装模式。"""

    if raw_value is None:
        return "json_object"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 body_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"json_object", "json_envelope"}:
        raise InvalidRequestError(
            f"{node_name} 的 body_mode 不支持当前取值",
            details={"body_mode": raw_value},
        )
    return normalized_value  # type: ignore[return-value]


def _read_on_missing_policy(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
    default_value: OnMissingPolicy,
) -> OnMissingPolicy:
    """读取缺失策略，未提供时使用默认值。"""

    if raw_value is None:
        return default_value
    return (
        _read_optional_on_missing_policy(
            raw_value=raw_value,
            node_name=node_name,
            field_name=field_name,
        )
        or default_value
    )


def _read_optional_on_missing_policy(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> OnMissingPolicy | None:
    """读取可选缺失策略。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"error", "skip", "null"}:
        raise InvalidRequestError(
            f"{node_name} 的 {field_name} 不支持当前取值",
            details={"on_missing": raw_value},
        )
    return normalized_value  # type: ignore[return-value]


def _read_optional_object_parameter(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> dict[str, object]:
    """读取可选对象参数。"""

    if raw_value is None:
        return {}
    normalized_value = build_value_payload(raw_value)["value"]
    if not isinstance(normalized_value, dict):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是对象")
    return normalized_value


def _read_required_non_empty_string(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> str:
    """读取必填非空字符串。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是非空字符串")
    return raw_value.strip()


def _read_optional_non_empty_string(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> str | None:
    """读取可选非空字符串。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None
