"""ZeroMQ TriggerSource 传输配置约束。"""

from __future__ import annotations

from math import isfinite
from typing import Mapping

from backend.service.application.errors import InvalidRequestError


ZEROMQ_BUFFER_TTL_SECONDS_KEY = "buffer_ttl_seconds"
ZEROMQ_RECEIVE_HWM_KEY = "receive_hwm"
ZEROMQ_SEND_HWM_KEY = "send_hwm"
ZEROMQ_MAX_MESSAGE_SIZE_BYTES_KEY = "max_message_size_bytes"
DEFAULT_ZEROMQ_BUFFER_TTL_SECONDS = 330.0
DEFAULT_ZEROMQ_RECEIVE_HWM = 1
DEFAULT_ZEROMQ_SEND_HWM = 1
DEFAULT_ZEROMQ_MAX_MESSAGE_SIZE_BYTES = 128 * 1024 * 1024


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


def resolve_zeromq_receive_hwm(
    transport_config: Mapping[str, object] | None,
) -> int:
    """读取 ZeroMQ 接收高水位，限制等待处理的高内存消息数量。"""

    return _resolve_positive_int(
        transport_config,
        key=ZEROMQ_RECEIVE_HWM_KEY,
        default=DEFAULT_ZEROMQ_RECEIVE_HWM,
    )


def resolve_zeromq_send_hwm(
    transport_config: Mapping[str, object] | None,
) -> int:
    """读取 ZeroMQ 发送高水位。"""

    return _resolve_positive_int(
        transport_config,
        key=ZEROMQ_SEND_HWM_KEY,
        default=DEFAULT_ZEROMQ_SEND_HWM,
    )


def resolve_zeromq_max_message_size_bytes(
    transport_config: Mapping[str, object] | None,
) -> int:
    """读取 ZeroMQ 单帧最大字节数，避免异常大消息耗尽进程内存。"""

    return _resolve_positive_int(
        transport_config,
        key=ZEROMQ_MAX_MESSAGE_SIZE_BYTES_KEY,
        default=DEFAULT_ZEROMQ_MAX_MESSAGE_SIZE_BYTES,
    )


def _resolve_positive_int(
    transport_config: Mapping[str, object] | None,
    *,
    key: str,
    default: int,
) -> int:
    """读取严格正整数 ZeroMQ transport 配置。"""

    raw_value = default
    if transport_config is not None and key in transport_config:
        raw_value = transport_config[key]
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value <= 0:
        raise InvalidRequestError(
            f"ZeroMQ {key} 必须是正整数",
            details={"field": f"transport_config.{key}", "value": raw_value},
        )
    return raw_value


def _build_invalid_ttl_error(value: object) -> InvalidRequestError:
    """构造一致的 ZeroMQ buffer TTL 校验错误。"""

    return InvalidRequestError(
        "ZeroMQ buffer_ttl_seconds 必须是大于 0 的有限数值",
        details={
            "field": f"transport_config.{ZEROMQ_BUFFER_TTL_SECONDS_KEY}",
            "value": value,
        },
    )
