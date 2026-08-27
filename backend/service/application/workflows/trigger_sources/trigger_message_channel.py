"""Workflow Trigger 在 LocalMessage Mailbox 上使用的版本化 envelope。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from backend.service.application.message_channels.codec import (
    decode_raw_json_object_envelope,
    encode_raw_json_object_envelope,
)
PREPARE_SCHEMA_ID = "amvision.workflow-trigger.prepare.v1"
ALLOCATION_SCHEMA_ID = "amvision.workflow-trigger.allocation.v1"
REQUEST_SCHEMA_ID = "amvision.workflow-trigger.request.v1"
RESPONSE_SCHEMA_ID = "amvision.workflow-trigger.response.v1"


@dataclass(frozen=True)
class WorkflowTriggerDescriptorIdentity:
    """固定一次 descriptor generation、owner 与 request identity。"""

    descriptor_index: int
    generation: int
    server_epoch: int
    request_id: UUID
    owner_token: int
    deadline_ns: int


@dataclass(frozen=True)
class WorkflowTriggerMailboxRequest:
    """描述 server 已原子 claim 的一条 REQUEST。"""

    identity: WorkflowTriggerDescriptorIdentity
    payload: bytes
    route_generation: int
    accepted_timeout_ms: int


@dataclass(frozen=True)
class WorkflowTriggerMailboxPrepare:
    """描述 server 已接受相对 timeout 的 PREPARE。"""

    identity: WorkflowTriggerDescriptorIdentity
    payload: bytes
    route_generation: int
    accepted_timeout_ms: int


class WorkflowTriggerMailboxServerPort(Protocol):
    """Workflow Trigger supervisor 所需的窄 mailbox port。"""

    def poll_prepare(self) -> WorkflowTriggerMailboxPrepare | None:
        """非阻塞取得一条 PREPARE。"""

    def tighten_accepted_timeout(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        timeout_ms: int,
    ) -> WorkflowTriggerDescriptorIdentity:
        """按 route 策略收紧 authoritative deadline。"""

    def publish_writing(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        allocation_payload: bytes,
    ) -> None:
        """发布 LocalBuffer allocation。"""

    def poll_request(self) -> WorkflowTriggerMailboxRequest | None:
        """非阻塞取得一条最终 REQUEST。"""

    def publish_response(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        payload: bytes,
        error_code: int,
        response_output_lease_count: int,
        handoff_state: int,
        response_ack_deadline_ns: int | None = None,
    ) -> int:
        """发布最终响应并返回实际公开错误码。"""

    def publish_error(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        error_code: int,
        message: str,
        expected_states: set[int] | None = None,
    ) -> int:
        """发布稳定错误。"""

    def new_response_ack_deadline_ns(self) -> int:
        """返回独立 response ACK deadline。"""

    def read_cancel_reason(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> int:
        """读取当前取消原因。"""

    def sweep(
        self,
        *,
        now_ns: int | None = None,
        descriptor_indexes: tuple[int, ...] | None = None,
    ) -> dict[str, object]:
        """推进终态并返回业务分类。"""

    def build_status(self) -> dict[str, object]:
        """返回不含正文的容量状态。"""

    def close(self) -> None:
        """有界关闭 owner。"""


def encode_trigger_payload(
    *,
    schema_id: str,
    payload: bytes,
    request_id: UUID,
) -> bytes:
    """把公开 JSON bytes 包装成通用不可变 wire envelope。"""

    return encode_raw_json_object_envelope(
        schema_id=schema_id,
        payload=payload,
        correlation_id=request_id,
    )


def decode_trigger_payload(
    wire_bytes: bytes,
    *,
    expected_schema_id: str,
    request_id: UUID,
) -> bytes:
    """校验 schema/correlation，并返回规范化紧凑 JSON bytes。"""

    return decode_raw_json_object_envelope(
        wire_bytes,
        expected_schema_id=expected_schema_id,
        correlation_id=request_id,
    )


__all__ = [
    "ALLOCATION_SCHEMA_ID",
    "PREPARE_SCHEMA_ID",
    "REQUEST_SCHEMA_ID",
    "RESPONSE_SCHEMA_ID",
    "WorkflowTriggerDescriptorIdentity",
    "WorkflowTriggerMailboxPrepare",
    "WorkflowTriggerMailboxRequest",
    "WorkflowTriggerMailboxServerPort",
    "decode_trigger_payload",
    "encode_trigger_payload",
]
