"""服务异常诊断信息序列化工具。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from backend.service.application.errors import ServiceError


DEFAULT_MAX_ERROR_TEXT_LENGTH = 24000


def serialize_error(
    error: BaseException,
    *,
    max_text_length: int = DEFAULT_MAX_ERROR_TEXT_LENGTH,
) -> dict[str, object]:
    """把异常转换为可持久化、可返回前端的诊断结构。

    参数：
    - error：待序列化的异常。
    - max_text_length：单个字符串字段最大长度，防止 stdout/stderr 过大撑爆任务记录。
    """

    error_message = error.message if isinstance(error, ServiceError) else str(error)
    payload: dict[str, object] = {
        "error_type": error.__class__.__name__,
        "error_message": _truncate_text(error_message, max_text_length),
    }
    if isinstance(error, ServiceError):
        payload.update(
            {
                "error_code": error.code,
                "status_code": error.status_code,
                "details": sanitize_error_value(error.details, max_text_length=max_text_length),
            }
        )
    return payload


def sanitize_error_value(
    value: Any,
    *,
    max_text_length: int = DEFAULT_MAX_ERROR_TEXT_LENGTH,
) -> object:
    """把错误细节转换为 JSON-safe 值。

    参数：
    - value：任意错误细节值。
    - max_text_length：单个字符串字段最大长度。
    """

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_text(value, max_text_length)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        preview = value[: min(len(value), 256)].decode("utf-8", errors="replace")
        return {
            "kind": "bytes",
            "size_bytes": len(value),
            "preview": _truncate_text(preview, max_text_length),
        }
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_error_value(item_value, max_text_length=max_text_length)
            for item_key, item_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_error_value(item, max_text_length=max_text_length) for item in value]
    return _truncate_text(str(value), max_text_length)


def _truncate_text(value: str, max_text_length: int) -> str:
    """按最大长度截断文本，同时保留被截断提示。"""

    if max_text_length <= 0 or len(value) <= max_text_length:
        return value
    omitted = len(value) - max_text_length
    return f"{value[:max_text_length]}\n... <truncated {omitted} chars>"
