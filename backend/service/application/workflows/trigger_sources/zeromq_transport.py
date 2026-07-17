"""ZeroMQ TriggerSource 传输配置约束。"""

from __future__ import annotations

from math import isfinite
from typing import Mapping

from backend.service.application.errors import InvalidRequestError


ZEROMQ_BUFFER_TTL_SECONDS_KEY = "buffer_ttl_seconds"
DEFAULT_ZEROMQ_BUFFER_TTL_SECONDS = 30.0


def resolve_zeromq_buffer_ttl_seconds(
    transport_config: Mapping[str, object] | None,
) -> float:
    """读取 ZeroMQ buffer TTL，并对历史配置补齐稳定默认值。"""

    raw_value: object = DEFAULT_ZEROMQ_BUFFER_TTL_SECONDS
    if transport_config is not None and ZEROMQ_BUFFER_TTL_SECONDS_KEY in transport_config:
        raw_value = transport_config[ZEROMQ_BUFFER_TTL_SECONDS_KEY]
    if isinstance(raw_value, bool):
        raise _build_invalid_ttl_error(raw_value)
    try:
        ttl_seconds = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise _build_invalid_ttl_error(raw_value) from exc
    if not isfinite(ttl_seconds) or ttl_seconds <= 0:
        raise _build_invalid_ttl_error(raw_value)
    return ttl_seconds


def _build_invalid_ttl_error(value: object) -> InvalidRequestError:
    """构造一致的 ZeroMQ buffer TTL 校验错误。"""

    return InvalidRequestError(
        "ZeroMQ buffer_ttl_seconds 必须是大于 0 的有限数值",
        details={
            "field": f"transport_config.{ZEROMQ_BUFFER_TTL_SECONDS_KEY}",
            "value": value,
        },
    )
