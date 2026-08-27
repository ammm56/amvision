"""Inference daemon 热路径的协议中立消息契约。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.message_channels.codec import (
    WireEnvelope,
    decode_wire_envelope,
    encode_wire_envelope,
)
from backend.service.application.errors import InvalidRequestError


INFERENCE_REQUEST_SCHEMA_ID = "inference-daemon.request.v1"
INFERENCE_RESPONSE_SCHEMA_ID = "inference-daemon.response.v1"


class InferenceMessageClient(Protocol):
    """供 application control client 使用的窄 inference RPC client。"""

    def request(
        self,
        payload: dict[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """执行一次不自动重试的本机 inference RPC。"""

    def close(self) -> None:
        """幂等关闭 client endpoint。"""


def encode_inference_request(payload: dict[str, object]) -> bytes:
    """编码 inference request envelope，并拒绝内联图片正文。"""

    reject_inline_image_bytes(payload)
    return encode_wire_envelope(
        WireEnvelope(
            schema_id=INFERENCE_REQUEST_SCHEMA_ID,
            payload=payload,  # type: ignore[arg-type]
        )
    )


def decode_inference_request(wire_bytes: bytes) -> dict[str, object]:
    """解码并严格校验 inference request envelope。"""

    envelope = decode_wire_envelope(wire_bytes)
    if envelope.schema_id != INFERENCE_REQUEST_SCHEMA_ID:
        raise InvalidRequestError("inference RPC request schema 不兼容")
    if not isinstance(envelope.payload, dict):
        raise InvalidRequestError("inference RPC request payload 必须是 JSON 对象")
    payload = dict(envelope.payload)
    reject_inline_image_bytes(payload)
    return payload


def encode_inference_response(payload: dict[str, object]) -> bytes:
    """编码 inference response envelope。"""

    return encode_wire_envelope(
        WireEnvelope(
            schema_id=INFERENCE_RESPONSE_SCHEMA_ID,
            payload=payload,  # type: ignore[arg-type]
        )
    )


def decode_inference_response(wire_bytes: bytes) -> dict[str, object]:
    """解码并严格校验 inference response envelope。"""

    envelope = decode_wire_envelope(wire_bytes)
    if envelope.schema_id != INFERENCE_RESPONSE_SCHEMA_ID:
        raise InvalidRequestError("inference RPC response schema 不兼容")
    if not isinstance(envelope.payload, dict):
        raise InvalidRequestError("inference RPC response payload 必须是 JSON 对象")
    return dict(envelope.payload)


def reject_inline_image_bytes(payload: dict[str, object]) -> None:
    """禁止图片 bytes/base64 进入结构化消息 Channel。"""

    def contains_image_content(value: object) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {
                    "input_image_bytes_base64",
                    "preview_image_bytes_base64",
                } and child not in (None, ""):
                    return True
                if contains_image_content(child):
                    return True
        elif isinstance(value, list | tuple):
            return any(contains_image_content(child) for child in value)
        return False

    if contains_image_content(payload):
        raise InvalidRequestError(
            "inference RPC 只传控制信息，图片必须使用 LocalBuffer 引用"
        )


__all__ = [
    "INFERENCE_REQUEST_SCHEMA_ID",
    "INFERENCE_RESPONSE_SCHEMA_ID",
    "InferenceMessageClient",
    "decode_inference_request",
    "decode_inference_response",
    "encode_inference_request",
    "encode_inference_response",
    "reject_inline_image_bytes",
]
