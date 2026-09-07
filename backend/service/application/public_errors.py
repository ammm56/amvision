"""公开错误对象构造与内部诊断字段收口。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from backend.contracts.errors import ErrorContract
from backend.service.application.errors import ServiceError


_ERROR_DEFAULTS_BY_STATE: dict[str, tuple[str, str]] = {
    "cancelled": ("operation_cancelled", "Workflow 执行已取消"),
    "failed": ("workflow_execution_failed", "Workflow 执行失败"),
    "timed_out": ("operation_timeout", "Workflow 执行超时"),
}
_INTERNAL_DETAIL_KEYS = frozenset(
    {
        "error_code",
        "error_message",
        "error_type",
        "exception",
        "stack",
        "stack_trace",
        "traceback",
    }
)


def build_error_contract(
    *,
    code: str,
    message: str,
    details: Mapping[str, object] | None = None,
) -> ErrorContract:
    """构造字段稳定且 JSON-safe 的公开错误对象。"""

    return ErrorContract(
        code=code.strip(),
        message=message.strip(),
        details=_sanitize_public_details(details or {}),
    )


def build_service_error_contract(error: ServiceError) -> ErrorContract:
    """把可公开的 ServiceError 转成统一错误对象。"""

    return build_error_contract(
        code=error.code,
        message=error.message,
        details=error.details,
    )


def build_workflow_error_contract(
    *,
    state: str,
    error_message: str | None,
    error_details: Mapping[str, object] | None,
) -> ErrorContract | None:
    """把 Workflow 内部终态错误字段映射为公开错误对象。

    非错误状态固定返回 None。失败记录缺少稳定错误码或摘要时，按 state
    补齐稳定默认值。内部异常类名、堆栈和重复错误字段不会进入公开 details。
    """

    defaults = _ERROR_DEFAULTS_BY_STATE.get(state)
    if defaults is None:
        return None
    default_code, default_message = defaults
    normalized_details = dict(error_details or {})
    raw_code = normalized_details.pop("error_code", None)
    code = (
        raw_code.strip()
        if isinstance(raw_code, str) and raw_code.strip()
        else default_code
    )
    message = (
        error_message.strip()
        if isinstance(error_message, str) and error_message.strip()
        else default_message
    )
    return build_error_contract(
        code=code,
        message=message,
        details=normalized_details,
    )


def without_public_error_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    """复制 metadata，并移除已经迁移到 error 的平行字段。"""

    result = dict(metadata)
    result.pop("error_code", None)
    result.pop("error_details", None)
    return result


def _sanitize_public_details(value: Mapping[str, object]) -> dict[str, object]:
    """移除内部诊断字段并生成 JSON-safe details。"""

    return {
        str(key): _sanitize_public_value(item)
        for key, item in value.items()
        if str(key).lower() not in _INTERNAL_DETAIL_KEYS
    }


def _sanitize_public_value(value: Any) -> object:
    """转换公开错误详情值，不预览 bytes 或本地 Path 内容。"""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes | bytearray | memoryview):
        return {"kind": "bytes", "size_bytes": len(value)}
    if isinstance(value, Path):
        return "<path>"
    if isinstance(value, Mapping):
        return _sanitize_public_details(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_public_value(item) for item in value]
    return type(value).__name__
