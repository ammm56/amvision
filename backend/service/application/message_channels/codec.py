"""LocalMessage transport 共用的紧凑 UTF-8 JSON envelope codec。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias
from uuid import UUID

from pydantic_core import from_json, to_json

from backend.service.application.message_channels.errors import (
    ChannelInvalidMessageError,
)


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class WireEnvelope:
    """Queue 与 mmap transport 共用的版本化结构化正文。"""

    schema_id: str
    payload: JsonValue
    correlation_id: UUID | None = None

    def __post_init__(self) -> None:
        """保证 schema id 可用于稳定路由。"""

        if not self.schema_id.strip():
            raise ValueError("WireEnvelope schema_id 不能为空")


def encode_wire_envelope(envelope: WireEnvelope) -> bytes:
    """编码为确定字段顺序的紧凑 UTF-8 JSON bytes。"""

    value: dict[str, JsonValue] = {
        "schema_id": envelope.schema_id,
        "payload": envelope.payload,
    }
    if envelope.correlation_id is not None:
        value["correlation_id"] = str(envelope.correlation_id)
    return bytes(to_json(value))


def decode_wire_envelope(wire_bytes: bytes) -> WireEnvelope:
    """解码并验证公开 envelope；transport 不调用该函数。"""

    try:
        value = from_json(wire_bytes)
    except (ValueError, TypeError) as error:
        raise ChannelInvalidMessageError("LocalMessage JSON 无法解码") from error
    if not isinstance(value, dict):
        raise ChannelInvalidMessageError("LocalMessage envelope 必须是对象")
    schema_id = value.get("schema_id")
    if not isinstance(schema_id, str) or not schema_id.strip():
        raise ChannelInvalidMessageError("LocalMessage schema_id 不合法")
    if "payload" not in value:
        raise ChannelInvalidMessageError("LocalMessage payload 缺失")
    correlation_id: UUID | None = None
    raw_correlation_id = value.get("correlation_id")
    if raw_correlation_id is not None:
        try:
            correlation_id = UUID(str(raw_correlation_id))
        except (ValueError, TypeError, AttributeError) as error:
            raise ChannelInvalidMessageError(
                "LocalMessage correlation_id 不合法"
            ) from error
    return WireEnvelope(
        schema_id=schema_id,
        payload=value["payload"],
        correlation_id=correlation_id,
    )


def encode_raw_json_object_envelope(
    *,
    schema_id: str,
    payload: bytes,
    correlation_id: UUID,
) -> bytes:
    """不构造大型 Python 对象树地包装已序列化 JSON object。

    输出与 ``encode_wire_envelope`` 的确定字段顺序逐字节一致。
    该快路径只检查 object 边界；业务 consumer 仍使用自身 typed
    schema 完成一次权威 JSON 校验。
    """

    return b"".join(
        encode_raw_json_object_envelope_segments(
            schema_id=schema_id,
            payload=payload,
            correlation_id=correlation_id,
        )
    )


def encode_raw_json_object_envelope_segments(
    *,
    schema_id: str,
    payload: bytes,
    correlation_id: UUID,
) -> tuple[bytes, bytes, bytes]:
    """返回逐字节等价的 prefix/body/suffix，供大正文单次发布。"""

    if not schema_id.strip():
        raise ValueError("WireEnvelope schema_id 不能为空")
    content = bytes(payload).strip()
    if len(content) < 2 or content[:1] != b"{" or content[-1:] != b"}":
        raise ChannelInvalidMessageError("LocalMessage payload 必须是 JSON object")
    prefix, suffix = _raw_json_object_envelope_fences(
        schema_id=schema_id,
        correlation_id=correlation_id,
    )
    return prefix, content, suffix


def decode_raw_json_object_envelope(
    wire_bytes: bytes,
    *,
    expected_schema_id: str,
    correlation_id: UUID,
) -> bytes:
    """按确定性 envelope fence 返回原始 JSON object 正文。"""

    content = bytes(wire_bytes)
    start, end = locate_raw_json_object_envelope(
        content,
        expected_schema_id=expected_schema_id,
        correlation_id=correlation_id,
    )
    return content[start:end]


def locate_raw_json_object_envelope(
    wire_bytes: bytes,
    *,
    expected_schema_id: str,
    correlation_id: UUID,
) -> tuple[int, int]:
    """校验确定性 fence 并返回不触发正文拷贝的范围。"""

    content = bytes(wire_bytes)
    prefix, suffix = _raw_json_object_envelope_fences(
        schema_id=expected_schema_id,
        correlation_id=correlation_id,
    )
    if (
        len(content) < len(prefix) + len(suffix) + 2
        or not content.startswith(prefix)
        or not content.endswith(suffix)
    ):
        raise ChannelInvalidMessageError("LocalMessage envelope identity 不匹配")
    payload_start = len(prefix)
    payload_end = len(content) - len(suffix)
    if (
        content[payload_start : payload_start + 1] != b"{"
        or content[payload_end - 1 : payload_end] != b"}"
    ):
        raise ChannelInvalidMessageError("LocalMessage payload 必须是 JSON object")
    return payload_start, payload_end


def _raw_json_object_envelope_fences(
    *,
    schema_id: str,
    correlation_id: UUID,
) -> tuple[bytes, bytes]:
    """生成与通用 compact JSON codec 一致的前后 fence。"""

    encoded_schema = bytes(to_json(schema_id))
    encoded_correlation = bytes(to_json(str(correlation_id)))
    return (
        b'{"schema_id":' + encoded_schema + b',"payload":',
        b',"correlation_id":' + encoded_correlation + b"}",
    )


__all__ = [
    "JsonScalar",
    "JsonValue",
    "WireEnvelope",
    "decode_raw_json_object_envelope",
    "decode_wire_envelope",
    "encode_raw_json_object_envelope",
    "encode_raw_json_object_envelope_segments",
    "encode_wire_envelope",
    "locate_raw_json_object_envelope",
]
