"""Workflow Trigger 在通用 LocalMessage Mailbox engine 上的两阶段 adapter。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
from threading import Lock
from time import monotonic_ns
from uuid import UUID, uuid4

from backend.contracts.ipc import workflow_trigger_mailbox_v1 as contract
from backend.contracts.ipc.local_message_profiles import (
    MAILBOX_PUBLIC_RESPONSE_CAPACITY_BYTES,
    WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.message_channels.errors import (
    ChannelCancelledError,
    ChannelCapacityExhaustedError,
    ChannelDeadlineExceededError,
    ChannelInvalidMessageError,
    LocalMessageChannelError,
)
from backend.service.application.message_channels.models import MailboxRequestContext
from backend.service.application.workflows.trigger_sources.trigger_message_channel import (
    ALLOCATION_SCHEMA_ID,
    EVENT_REQUEST_SCHEMA_ID,
    PREPARE_SCHEMA_ID,
    REQUEST_SCHEMA_ID,
    RESPONSE_SCHEMA_ID,
    WorkflowTriggerDescriptorIdentity,
    WorkflowTriggerMailboxPrepare,
    WorkflowTriggerMailboxRequest,
    decode_trigger_payload,
    encode_trigger_payload,
)
from backend.service.application.message_channels.codec import (
    encode_raw_json_object_envelope_segments,
    locate_raw_json_object_envelope,
)
from backend.service.infrastructure.ipc.local_message.common_layout import (
    MAILBOX_ERROR_CANCELLED,
    MAILBOX_ERROR_CAPACITY_EXHAUSTED,
    MAILBOX_ERROR_DEADLINE_EXCEEDED,
    MAILBOX_ERROR_INVALID_MESSAGE,
    MAILBOX_ERROR_NONE,
    MAILBOX_ERROR_SERVER_FAILURE,
    MAILBOX_STATE_FREE,
    MAILBOX_STATE_PROCESSING,
    mailbox_layout,
)
from backend.service.infrastructure.ipc.local_message.paths import (
    build_workflow_trigger_mailbox_paths,
    reject_legacy_workflow_trigger_layout,
)
from backend.service.infrastructure.ipc.local_message.mailbox import (
    MmapMailboxClient,
    MmapMailboxServer,
    MailboxTerminalReason,
    MailboxTransportIdentity,
)


DESCRIPTOR_STRIDE_BYTES = mailbox_layout(
    WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1
).descriptor_stride_bytes
MAILBOX_FILE_SIZE_BYTES = mailbox_layout(
    WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1
).file_size_bytes


@dataclass(frozen=True)
class WorkflowTriggerMailboxAllocation:
    """描述 server 发布的 LocalBuffer allocation。"""

    identity: WorkflowTriggerDescriptorIdentity
    payload: bytes


@dataclass(frozen=True)
class WorkflowTriggerMailboxResponse:
    """描述 client 已复制、尚未 ACK 的最终响应。"""

    identity: WorkflowTriggerDescriptorIdentity
    _wire_payload: bytes
    _payload_start: int
    _payload_end: int
    error_code: int
    response_output_lease_count: int
    handoff_state: int
    response_ack_deadline_ns: int

    @property
    def payload(self) -> bytes:
        """在业务确实需要 bytes 时才物化 envelope 内的 JSON 正文。"""

        if self._payload_start == 0 and self._payload_end == len(self._wire_payload):
            return self._wire_payload
        return self._wire_payload[self._payload_start : self._payload_end]

    @property
    def payload_size(self) -> int:
        """不拷贝正文地返回公开 JSON 长度。"""

        return self._payload_end - self._payload_start

    def json_payload(self) -> dict[str, object]:
        """把 UTF-8 JSON response 解码为对象。"""

        value = json.loads(self.payload.decode("utf-8"))
        if not isinstance(value, dict):
            raise InvalidRequestError("Workflow Trigger response JSON 必须是对象")
        return value


def _transport_key(identity: WorkflowTriggerDescriptorIdentity) -> tuple[int, ...]:
    """返回不包含可收紧 deadline 的稳定 transport fence。"""

    return (
        identity.descriptor_index,
        identity.generation,
        identity.server_epoch,
        identity.owner_token,
    )


def _to_transport_identity(
    identity: WorkflowTriggerDescriptorIdentity,
) -> MailboxTransportIdentity:
    """把业务 identity 投影为通用 Mailbox fence。"""

    return MailboxTransportIdentity(
        descriptor_index=identity.descriptor_index,
        generation=identity.generation,
        owner_epoch=identity.server_epoch,
        owner_token=identity.owner_token,
    )


def _unpack_extension(content: bytes) -> tuple[int, ...]:
    """把损坏扩展统一映射为公开请求错误。"""

    try:
        return contract.unpack_descriptor_extension(content)
    except (ValueError, TypeError) as error:
        raise InvalidRequestError(
            "Workflow Trigger descriptor extension 损坏"
        ) from error


class WorkflowTriggerMailboxServer:
    """保留 Trigger 业务状态机，复用通用 Mailbox descriptor/page allocator。"""

    def __init__(
        self,
        *,
        buffers_root: str | Path,
        max_request_timeout_ms: int = 120_000,
        response_ack_timeout_ms: int = 30_000,
    ) -> None:
        """创建唯一 Trigger Mailbox owner。"""

        if max_request_timeout_ms <= 0:
            raise ServiceConfigurationError(
                "Workflow Trigger 最大请求 timeout 必须大于 0"
            )
        if response_ack_timeout_ms <= 0:
            raise ServiceConfigurationError(
                "Workflow Trigger response ACK timeout 必须大于 0"
            )
        reject_legacy_workflow_trigger_layout(buffers_root=buffers_root)
        self.paths = build_workflow_trigger_mailbox_paths(
            buffers_root=buffers_root
        )
        self.path = self.paths.mmap_path
        self.max_request_timeout_ms = max_request_timeout_ms
        self.response_ack_timeout_ms = response_ack_timeout_ms
        self._mailbox = MmapMailboxServer(
            paths=self.paths,
            profile=WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1,
            response_ack_timeout_seconds=response_ack_timeout_ms / 1_000,
        )
        self.server_epoch = self._mailbox.owner_epoch
        self._contexts: dict[tuple[int, ...], MailboxRequestContext] = {}
        self._identities: dict[tuple[int, ...], WorkflowTriggerDescriptorIdentity] = {}
        self._extensions: dict[tuple[int, ...], tuple[int, ...]] = {}
        self._prepare_queue: deque[tuple[MailboxRequestContext, tuple[int, ...]]] = deque()
        self._request_queue: deque[tuple[MailboxRequestContext, tuple[int, ...]]] = deque()
        self._lock = Lock()
        self._last_timeout_diagnostic: dict[str, int] | None = None

    def poll_prepare(self) -> WorkflowTriggerMailboxPrepare | None:
        """非阻塞取得 PREPARE，并只在 server 侧建立 absolute deadline。"""

        received = self._poll_phase(contract.DESCRIPTOR_STATE_PREPARE)
        if received is None:
            return None
        context, extension = received
        requested_timeout_ms = int(extension[2])
        accepted_timeout_ms = min(
            max(requested_timeout_ms, 1),
            self.max_request_timeout_ms,
        )
        accepted_at_ns = monotonic_ns()
        updated_extension = contract.pack_descriptor_extension(
            phase=contract.DESCRIPTOR_STATE_PREPARE,
            requested_timeout_ms=requested_timeout_ms,
            accepted_timeout_ms=accepted_timeout_ms,
            route_generation=int(extension[4]),
        )
        context = self._mailbox.update_processing_deadline(
            context,
            deadline_ns=accepted_at_ns + accepted_timeout_ms * 1_000_000,
            descriptor_extension=updated_extension,
        )
        identity = self._identity(context)
        self._remember(
            identity,
            context,
            extension=_unpack_extension(updated_extension),
        )
        self._last_timeout_diagnostic = {
            "requested_timeout_ms": requested_timeout_ms,
            "accepted_timeout_ms": accepted_timeout_ms,
            "accepted_at_ns": accepted_at_ns,
        }
        try:
            payload = decode_trigger_payload(
                context.wire_bytes,
                expected_schema_id=PREPARE_SCHEMA_ID,
                request_id=context.request_id,
            )
        except ChannelInvalidMessageError as error:
            self.publish_error(
                identity=identity,
                error_code=contract.ERROR_CODE_INVALID_REQUEST,
                message=str(error),
            )
            return None
        return WorkflowTriggerMailboxPrepare(
            identity=identity,
            payload=payload,
            route_generation=int(extension[4]),
            accepted_timeout_ms=accepted_timeout_ms,
        )

    def tighten_accepted_timeout(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        timeout_ms: int,
    ) -> WorkflowTriggerDescriptorIdentity:
        """按 route 上限收紧 deadline，不从当前时间重新起算。"""

        if timeout_ms <= 0:
            raise InvalidRequestError("Workflow Trigger 路由 timeout 必须大于 0")
        context = self._require_context(identity)
        extension = self._require_extension(identity)
        current_timeout_ms = int(extension[3])
        accepted_timeout_ms = min(current_timeout_ms, timeout_ms)
        accepted_at_ns = identity.deadline_ns - current_timeout_ms * 1_000_000
        updated_extension = contract.pack_descriptor_extension(
                phase=int(extension[0]),
                requested_timeout_ms=int(extension[2]),
                accepted_timeout_ms=accepted_timeout_ms,
                route_generation=int(extension[4]),
        )
        context = self._mailbox.update_processing_deadline(
            context,
            deadline_ns=accepted_at_ns + accepted_timeout_ms * 1_000_000,
            descriptor_extension=updated_extension,
        )
        updated = self._identity(context)
        self._remember(
            updated,
            context,
            extension=_unpack_extension(updated_extension),
        )
        return updated

    def publish_writing(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        allocation_payload: bytes,
    ) -> None:
        """以内联 response 发布 allocation，client 读取后复用 descriptor。"""

        context = self._require_context(identity)
        wire_bytes = self._encode(
            schema_id=ALLOCATION_SCHEMA_ID,
            payload=allocation_payload,
            request_id=identity.request_id,
        )
        if len(wire_bytes) > WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1.inline_response_capacity_bytes:
            raise InvalidRequestError(
                "Workflow Trigger allocation envelope 超过 64 KiB inline 上限"
            )
        extension = self._require_extension(identity)
        updated_extension = contract.pack_descriptor_extension(
                phase=contract.DESCRIPTOR_STATE_WRITING,
                requested_timeout_ms=int(extension[2]),
                accepted_timeout_ms=int(extension[3]),
                route_generation=int(extension[4]),
        )
        self._mailbox.publish_response(
            context,
            wire_bytes=wire_bytes,
            descriptor_extension=updated_extension,
        )
        self._forget_context(identity)

    def poll_request(self) -> WorkflowTriggerMailboxRequest | None:
        """非阻塞取得图片请求或无图片事件请求。"""

        received = self._poll_phase(contract.DESCRIPTOR_STATE_REQUEST)
        if received is None:
            return None
        context, extension = received
        identity = self._identity(context)
        self._remember(identity, context, extension=extension)
        try:
            try:
                payload = decode_trigger_payload(
                    context.wire_bytes,
                    expected_schema_id=EVENT_REQUEST_SCHEMA_ID,
                    request_id=context.request_id,
                )
                request_schema_id = EVENT_REQUEST_SCHEMA_ID
            except ChannelInvalidMessageError:
                payload = decode_trigger_payload(
                    context.wire_bytes,
                    expected_schema_id=REQUEST_SCHEMA_ID,
                    request_id=context.request_id,
                )
                request_schema_id = REQUEST_SCHEMA_ID
        except ChannelInvalidMessageError as error:
            self.publish_error(
                identity=identity,
                error_code=contract.ERROR_CODE_INVALID_REQUEST,
                message=str(error),
            )
            return None
        accepted_timeout_ms = int(extension[3])
        if request_schema_id == EVENT_REQUEST_SCHEMA_ID:
            if accepted_timeout_ms != 0:
                self.publish_error(
                    identity=identity,
                    error_code=contract.ERROR_CODE_PROTOCOL_ERROR,
                    message="无图片事件请求不能复用图片 PREPARE 上下文",
                )
                return None
            requested_timeout_ms = int(extension[2])
            accepted_timeout_ms = min(
                max(requested_timeout_ms, 1),
                self.max_request_timeout_ms,
            )
            accepted_at_ns = monotonic_ns()
            updated_extension = contract.pack_descriptor_extension(
                phase=contract.DESCRIPTOR_STATE_REQUEST,
                requested_timeout_ms=requested_timeout_ms,
                accepted_timeout_ms=accepted_timeout_ms,
                route_generation=int(extension[4]),
            )
            context = self._mailbox.update_processing_deadline(
                context,
                deadline_ns=accepted_at_ns + accepted_timeout_ms * 1_000_000,
                descriptor_extension=updated_extension,
            )
            identity = self._identity(context)
            extension = _unpack_extension(updated_extension)
            self._remember(identity, context, extension=extension)
            self._last_timeout_diagnostic = {
                "requested_timeout_ms": requested_timeout_ms,
                "accepted_timeout_ms": accepted_timeout_ms,
                "accepted_at_ns": accepted_at_ns,
            }
        elif accepted_timeout_ms <= 0:
            self.publish_error(
                identity=identity,
                error_code=contract.ERROR_CODE_PROTOCOL_ERROR,
                message="图片 v1 REQUEST 缺少 PREPARE 接受上下文",
            )
            return None
        return WorkflowTriggerMailboxRequest(
            identity=identity,
            payload=payload,
            route_generation=int(extension[4]),
            accepted_timeout_ms=accepted_timeout_ms,
            request_schema_id=request_schema_id,
        )

    def publish_response(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        payload: bytes,
        error_code: int = contract.ERROR_CODE_NONE,
        response_output_lease_count: int = 0,
        handoff_state: int = contract.HANDOFF_STATE_NONE,
        response_ack_deadline_ns: int | None = None,
    ) -> int:
        """通过通用压缩/page-chain 发布一次最终响应。"""

        context = self._require_context(identity)
        wire_segments = self._encode_segments(
            schema_id=RESPONSE_SCHEMA_ID,
            payload=payload,
            request_id=identity.request_id,
        )
        wire_size = sum(len(segment) for segment in wire_segments)
        if (
            len(payload) > MAILBOX_PUBLIC_RESPONSE_CAPACITY_BYTES
            or wire_size > WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1.max_response_bytes
        ):
            error_code = contract.ERROR_CODE_TRIGGER_RESPONSE_TOO_LARGE
            response_output_lease_count = 0
            handoff_state = contract.HANDOFF_STATE_NONE
            wire_segments = self._encode_segments(
                schema_id=RESPONSE_SCHEMA_ID,
                payload=json.dumps(
                    {
                        "state": "failed",
                        "error_code": error_code,
                        "error_message": "Workflow Trigger response 超过 32 MiB 公开正文上限",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8"),
                request_id=identity.request_id,
            )
        extension = self._require_extension(identity)
        updated_extension = contract.pack_descriptor_extension(
                phase=contract.DESCRIPTOR_STATE_RESPONSE,
                cancel_reason=int(extension[1]),
                requested_timeout_ms=int(extension[2]),
                accepted_timeout_ms=int(extension[3]),
                route_generation=int(extension[4]),
                error_code=error_code,
                response_output_lease_count=response_output_lease_count,
                handoff_state=handoff_state,
        )
        try:
            self._mailbox.publish_response_segments_with_receipt(
                context,
                wire_segments=wire_segments,
                response_ack_deadline_ns=response_ack_deadline_ns,
                descriptor_extension=updated_extension,
            )
            return error_code
        except ChannelCapacityExhaustedError:
            return contract.ERROR_CODE_TRIGGER_RESPONSE_CAPACITY_EXHAUSTED
        except ChannelDeadlineExceededError:
            return contract.ERROR_CODE_DEADLINE_EXCEEDED
        except ChannelCancelledError:
            return contract.ERROR_CODE_CANCELLED
        finally:
            self._forget_context(identity)

    def publish_json_response(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        payload: dict[str, object],
        error_code: int = contract.ERROR_CODE_NONE,
        response_output_lease_count: int = 0,
        handoff_state: int = contract.HANDOFF_STATE_NONE,
    ) -> int:
        """生成紧凑 UTF-8 JSON 并发布。"""

        return self.publish_response(
            identity=identity,
            payload=json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
            error_code=error_code,
            response_output_lease_count=response_output_lease_count,
            handoff_state=handoff_state,
        )

    def publish_error(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        error_code: int,
        message: str,
        expected_states: set[int] | None = None,
    ) -> int:
        """发布不包含图片 locator 的稳定 JSON 错误。"""

        del expected_states
        return self.publish_json_response(
            identity=identity,
            payload={
                "state": "failed",
                "error_code": error_code,
                "error_message": message,
            },
            error_code=error_code,
        )

    def new_response_ack_deadline_ns(self) -> int:
        """生成和通用 Mailbox owner 配置一致的 ACK deadline。"""

        return monotonic_ns() + self.response_ack_timeout_ms * 1_000_000

    def read_cancel_reason(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> int:
        """读取 PROCESSING descriptor 的业务 cancel reason。"""

        context = self._require_context(identity)
        return int(self._read_extension(context)[1])

    def sweep(
        self,
        *,
        now_ns: int | None = None,
        descriptor_indexes: tuple[int, ...] | None = None,
    ) -> dict[str, object]:
        """把通用 transport 终态映射为 Trigger 生命周期分类。"""

        self._mailbox.sweep(
            now_ns=now_ns,
            descriptor_indexes=descriptor_indexes,
        )
        cancelled: list[WorkflowTriggerDescriptorIdentity] = []
        deadlines: list[WorkflowTriggerDescriptorIdentity] = []
        ack_timeouts: list[WorkflowTriggerDescriptorIdentity] = []
        released: list[WorkflowTriggerDescriptorIdentity] = []
        for event in self._mailbox.drain_terminal_events():
            key = (
                event.identity.descriptor_index,
                event.identity.generation,
                event.identity.owner_epoch,
                event.identity.owner_token,
            )
            with self._lock:
                identity = self._identities.get(key)
            if identity is None:
                identity = WorkflowTriggerDescriptorIdentity(
                    descriptor_index=event.identity.descriptor_index,
                    generation=event.identity.generation,
                    server_epoch=event.identity.owner_epoch,
                    request_id=event.request_id,
                    owner_token=event.identity.owner_token,
                    deadline_ns=0,
                )
            if event.reason == MailboxTerminalReason.CANCELLED:
                cancelled.append(identity)
            elif event.reason == MailboxTerminalReason.DEADLINE_EXCEEDED:
                deadlines.append(identity)
            elif event.reason == MailboxTerminalReason.RESPONSE_ACK_TIMEOUT:
                ack_timeouts.append(identity)
            elif event.reason == MailboxTerminalReason.ACKNOWLEDGED:
                released.append(identity)
            if event.reason in {
                MailboxTerminalReason.ACKNOWLEDGED,
                MailboxTerminalReason.RESPONSE_ACK_TIMEOUT,
                MailboxTerminalReason.CANCELLED,
            }:
                with self._lock:
                    self._identities.pop(key, None)
                    self._contexts.pop(key, None)
                    self._extensions.pop(key, None)
        return {
            "cancelled_count": len(cancelled),
            "deadline_exceeded_count": len(deadlines),
            "response_ack_timeout_count": len(ack_timeouts),
            "released_count": len(released),
            "cancelled_identities": tuple(cancelled),
            "deadline_exceeded_identities": tuple(deadlines),
            "response_ack_timeout_identities": tuple(ack_timeouts),
            "released_identities": tuple(released),
        }

    def build_status(self) -> dict[str, object]:
        """返回与现有 health API 兼容的无内容容量摘要。"""

        state_counts = [0] * 8
        for transport_state, extension_bytes in self._mailbox.descriptor_statuses():
            if transport_state == MAILBOX_STATE_FREE:
                state_counts[contract.DESCRIPTOR_STATE_FREE] += 1
                continue
            phase = int(_unpack_extension(extension_bytes)[0])
            if transport_state == MAILBOX_STATE_PROCESSING:
                phase = contract.DESCRIPTOR_STATE_PROCESSING
            if 0 <= phase < len(state_counts):
                state_counts[phase] += 1
        health = self._mailbox.health()
        return {
            "contract_id": contract.CONTRACT_ID,
            "path": str(self.path),
            "server_epoch": self.server_epoch,
            "file_size_bytes": MAILBOX_FILE_SIZE_BYTES,
            "descriptor_state_counts": tuple(state_counts),
            "free_page_count": health.free_pages,
            "used_page_count": (
                WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1.overflow_page_count
                - health.free_pages
            ),
            "last_timeout_diagnostic": (
                dict(self._last_timeout_diagnostic)
                if self._last_timeout_diagnostic is not None
                else None
            ),
        }

    def close(self) -> None:
        """有界关闭通用 Mailbox owner。"""

        self._mailbox.close(deadline_ns=monotonic_ns() + 2_000_000_000)

    def __enter__(self) -> WorkflowTriggerMailboxServer:
        """返回 server context。"""

        return self

    def __exit__(self, *_args: object) -> None:
        """退出时释放 owner。"""

        self.close()

    def _poll_phase(
        self,
        expected_phase: int,
    ) -> tuple[MailboxRequestContext, tuple[int, ...]] | None:
        """按扩展 phase 分流通用 REQUEST，不维护第二套 descriptor scanner。"""

        queue = (
            self._prepare_queue
            if expected_phase == contract.DESCRIPTOR_STATE_PREPARE
            else self._request_queue
        )
        if queue:
            return queue.popleft()
        while True:
            # Trigger supervisor 在同一次 process_once 末尾统一执行带活动集合的
            # terminal sweep；此处只扫描 request，避免每个 phase 重复全表扫描。
            received = self._mailbox.receive_with_extension(
                deadline_ns=monotonic_ns() + 1,
                sweep_before_receive=False,
            )
            if received is None:
                return None
            context, extension_bytes = received
            extension = _unpack_extension(extension_bytes)
            phase = int(extension[0])
            if phase == expected_phase:
                return context, extension
            if phase == contract.DESCRIPTOR_STATE_PREPARE:
                self._prepare_queue.append((context, extension))
            elif phase == contract.DESCRIPTOR_STATE_REQUEST:
                self._request_queue.append((context, extension))
            else:
                self._mailbox.publish_failure(context)

    def _read_extension(self, context: MailboxRequestContext) -> tuple[int, ...]:
        """读取并解码当前 PROCESSING extension。"""

        return _unpack_extension(self._mailbox.read_processing_extension(context))

    def _identity(self, context: MailboxRequestContext) -> WorkflowTriggerDescriptorIdentity:
        """从通用 request context 构造业务 identity。"""

        transport = self._mailbox.transport_identity(context)
        return WorkflowTriggerDescriptorIdentity(
            descriptor_index=transport.descriptor_index,
            generation=transport.generation,
            server_epoch=transport.owner_epoch,
            request_id=context.request_id,
            owner_token=transport.owner_token,
            deadline_ns=context.deadline_ns,
        )

    def _remember(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
        context: MailboxRequestContext,
        *,
        extension: tuple[int, ...] | None = None,
    ) -> None:
        """登记 descriptor 外的 Python context，不承担资源所有权。"""

        key = _transport_key(identity)
        with self._lock:
            self._identities[key] = identity
            self._contexts[key] = context
            if extension is not None:
                self._extensions[key] = extension

    def _forget_context(self, identity: WorkflowTriggerDescriptorIdentity) -> None:
        """response 发布后仅移除 handler context，保留终态 identity。"""

        with self._lock:
            self._contexts.pop(_transport_key(identity), None)

    def _require_context(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> MailboxRequestContext:
        """按完整 transport fence 取得当前 handler context。"""

        with self._lock:
            context = self._contexts.get(_transport_key(identity))
        if context is None:
            raise InvalidRequestError("Workflow Trigger descriptor identity 不存在")
        return context

    def _require_extension(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> tuple[int, ...]:
        """取得当前 handler 已验证的扩展快照。"""

        with self._lock:
            extension = self._extensions.get(_transport_key(identity))
        if extension is None:
            raise InvalidRequestError("Workflow Trigger descriptor 扩展不存在")
        return extension

    @staticmethod
    def _encode(*, schema_id: str, payload: bytes, request_id: UUID) -> bytes:
        """编码并把 codec 错误映射为公开请求错误。"""

        try:
            return encode_trigger_payload(
                schema_id=schema_id,
                payload=payload,
                request_id=request_id,
            )
        except ChannelInvalidMessageError as error:
            raise InvalidRequestError(str(error)) from error

    @staticmethod
    def _encode_segments(
        *,
        schema_id: str,
        payload: bytes,
        request_id: UUID,
    ) -> tuple[bytes, bytes, bytes]:
        """编码大正文的等价分段 envelope，避免额外整块拷贝。"""

        try:
            return encode_raw_json_object_envelope_segments(
                schema_id=schema_id,
                payload=payload,
                correlation_id=request_id,
            )
        except ChannelInvalidMessageError as error:
            raise InvalidRequestError(str(error)) from error

class WorkflowTriggerMailboxClient:
    """Python SDK harness；.NET SDK 使用相同 common/Mailbox/extension contract。"""

    def __init__(self, *, buffers_root: str | Path) -> None:
        """连接全局 Trigger Mailbox owner。"""

        self.paths = build_workflow_trigger_mailbox_paths(
            buffers_root=buffers_root
        )
        self.path = self.paths.mmap_path
        try:
            self._mailbox = MmapMailboxClient(
                paths=self.paths,
                profile=WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1,
            )
        except LocalMessageChannelError as error:
            raise ServiceConfigurationError(
                "Workflow Trigger mailbox 尚未启动",
                details={"path": str(self.path)},
            ) from error
        self._request_ids: dict[tuple[int, ...], UUID] = {}

    @property
    def server_epoch(self) -> int:
        """返回连接时可见的 owner epoch。"""

        return self._mailbox.owner_epoch

    def claim(
        self,
        *,
        timeout_ms: int,
        route_generation: int,
        prepare_payload: bytes = b"{}",
        request_id: UUID | None = None,
    ) -> WorkflowTriggerDescriptorIdentity:
        """满载立即拒绝地发布 PREPARE。"""

        return self._claim(
            timeout_ms=timeout_ms,
            route_generation=route_generation,
            payload=prepare_payload,
            request_id=request_id,
            schema_id=PREPARE_SCHEMA_ID,
            phase=contract.DESCRIPTOR_STATE_PREPARE,
            envelope_name="PREPARE",
        )

    def claim_event(
        self,
        *,
        timeout_ms: int,
        route_generation: int,
        event_payload: bytes,
        request_id: UUID | None = None,
    ) -> WorkflowTriggerDescriptorIdentity:
        """直接发布无图片事件 REQUEST，不创建图片 allocation。"""

        return self._claim(
            timeout_ms=timeout_ms,
            route_generation=route_generation,
            payload=event_payload,
            request_id=request_id,
            schema_id=EVENT_REQUEST_SCHEMA_ID,
            phase=contract.DESCRIPTOR_STATE_REQUEST,
            envelope_name="event-only REQUEST",
        )

    def _claim(
        self,
        *,
        timeout_ms: int,
        route_generation: int,
        payload: bytes,
        request_id: UUID | None,
        schema_id: str,
        phase: int,
        envelope_name: str,
    ) -> WorkflowTriggerDescriptorIdentity:
        """按明确 schema/phase 单次 claim 一个 descriptor。"""

        if timeout_ms <= 0 or timeout_ms > 0xFFFFFFFF:
            raise InvalidRequestError(
                "Workflow Trigger timeout_ms 必须位于 1..4294967295"
            )
        resolved_request_id = request_id or uuid4()
        wire_bytes = self._encode(
            schema_id=schema_id,
            payload=payload,
            request_id=resolved_request_id,
        )
        if len(wire_bytes) > WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1.max_request_bytes:
            raise InvalidRequestError(
                f"Workflow Trigger {envelope_name} envelope 超过 64 KiB 上限"
            )
        extension = contract.pack_descriptor_extension(
            phase=phase,
            requested_timeout_ms=timeout_ms,
            route_generation=route_generation,
        )
        try:
            transport = self._mailbox.claim_prepared(
                request_id=resolved_request_id,
                wire_bytes=wire_bytes,
                claim_deadline_ns=monotonic_ns() + 50_000_000,
                descriptor_extension=extension,
            )
        except LocalMessageChannelError as error:
            raise InvalidRequestError(str(error)) from error
        identity = WorkflowTriggerDescriptorIdentity(
            descriptor_index=transport.descriptor_index,
            generation=transport.generation,
            server_epoch=transport.owner_epoch,
            request_id=resolved_request_id,
            owner_token=transport.owner_token,
            deadline_ns=0,
        )
        self._request_ids[_transport_key(identity)] = resolved_request_id
        return identity

    def read_writing_allocation(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> WorkflowTriggerMailboxAllocation | None:
        """读取 allocation 后立即转入 WRITING_REQUEST，ACK 仍留到最终响应。"""

        snapshot = self._snapshot(identity)
        if snapshot is None:
            return None
        extension = _unpack_extension(snapshot.extension)
        if int(extension[0]) != contract.DESCRIPTOR_STATE_WRITING:
            return None
        self._raise_transport_error(snapshot.error_code)
        payload = self._decode(
            snapshot.wire_bytes,
            expected_schema_id=ALLOCATION_SCHEMA_ID,
            request_id=identity.request_id,
        )
        current = WorkflowTriggerDescriptorIdentity(
            descriptor_index=identity.descriptor_index,
            generation=identity.generation,
            server_epoch=identity.server_epoch,
            request_id=identity.request_id,
            owner_token=identity.owner_token,
            deadline_ns=snapshot.deadline_ns,
        )
        self._mailbox.reopen_response_for_request(
            _to_transport_identity(current),
            descriptor_extension=contract.pack_descriptor_extension(
                phase=contract.DESCRIPTOR_STATE_WRITING,
                requested_timeout_ms=int(extension[2]),
                accepted_timeout_ms=int(extension[3]),
                route_generation=int(extension[4]),
            ),
        )
        return WorkflowTriggerMailboxAllocation(identity=current, payload=payload)

    def publish_request(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        payload: bytes,
    ) -> None:
        """写完图片后发布最终结构化 REQUEST。"""

        wire_bytes = self._encode(
            schema_id=REQUEST_SCHEMA_ID,
            payload=payload,
            request_id=identity.request_id,
        )
        if len(wire_bytes) > WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1.max_request_bytes:
            raise InvalidRequestError(
                "Workflow Trigger request envelope 超过 64 KiB 上限"
            )
        # route/原始 timeout 从 WRITING extension 保留；通用 API 会完整覆盖，
        # 因此先读取当前 extension 并只替换 phase。
        current_extension = self._read_active_extension(identity)
        values = _unpack_extension(current_extension)
        snapshot_extension = contract.pack_descriptor_extension(
            phase=contract.DESCRIPTOR_STATE_REQUEST,
            requested_timeout_ms=int(values[2]),
            accepted_timeout_ms=int(values[3]),
            route_generation=int(values[4]),
        )
        try:
            self._mailbox.publish_reopened_request(
                _to_transport_identity(identity),
                wire_bytes=wire_bytes,
                descriptor_extension=snapshot_extension,
            )
        except LocalMessageChannelError as error:
            raise InvalidRequestError(str(error)) from error

    def read_response(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> WorkflowTriggerMailboxResponse | None:
        """复制最终响应；output attachment 释放前不 ACK。"""

        snapshot = self._snapshot(identity)
        if snapshot is None:
            return None
        extension = _unpack_extension(snapshot.extension)
        phase = int(extension[0])
        business_error = int(extension[5])
        if snapshot.error_code != MAILBOX_ERROR_NONE:
            business_error = _business_error_from_transport(snapshot.error_code)
            payload = json.dumps(
                {"state": "failed", "error": {"code": business_error}},
                separators=(",", ":"),
            ).encode("utf-8")
            payload_start = 0
            payload_end = len(payload)
        elif phase == contract.DESCRIPTOR_STATE_RESPONSE:
            payload = snapshot.wire_bytes
            try:
                payload_start, payload_end = locate_raw_json_object_envelope(
                    payload,
                    expected_schema_id=RESPONSE_SCHEMA_ID,
                    correlation_id=identity.request_id,
                )
            except ChannelInvalidMessageError as error:
                raise InvalidRequestError(str(error)) from error
        else:
            return None
        current = WorkflowTriggerDescriptorIdentity(
            descriptor_index=identity.descriptor_index,
            generation=identity.generation,
            server_epoch=identity.server_epoch,
            request_id=identity.request_id,
            owner_token=identity.owner_token,
            deadline_ns=snapshot.deadline_ns,
        )
        return WorkflowTriggerMailboxResponse(
            identity=current,
            _wire_payload=payload,
            _payload_start=payload_start,
            _payload_end=payload_end,
            error_code=business_error,
            response_output_lease_count=int(extension[6]),
            handoff_state=int(extension[7]),
            response_ack_deadline_ns=snapshot.response_ack_deadline_ns,
        )

    def acknowledge(self, *, identity: WorkflowTriggerDescriptorIdentity) -> None:
        """幂等发布最终 response ACK。"""

        self._mailbox.acknowledge(_to_transport_identity(identity))

    def cancel(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        reason: int = contract.CANCEL_REASON_EXPLICIT,
    ) -> None:
        """在任一活动 phase 发布 cancel reason 与 transport cancel flag。"""

        if reason not in {
            contract.CANCEL_REASON_REQUEST_TIMEOUT,
            contract.CANCEL_REASON_EXPLICIT,
            contract.CANCEL_REASON_CLIENT_SHUTDOWN,
        }:
            raise InvalidRequestError("Workflow Trigger cancel reason 不合法")
        try:
            values = _unpack_extension(self._read_active_extension(identity))
            extension = contract.pack_descriptor_extension(
                phase=int(values[0]),
                cancel_reason=reason,
                requested_timeout_ms=int(values[2]),
                accepted_timeout_ms=int(values[3]),
                route_generation=int(values[4]),
                error_code=int(values[5]),
                response_output_lease_count=int(values[6]),
                handoff_state=int(values[7]),
            )
            self._mailbox.request_cancel(
                _to_transport_identity(identity),
                descriptor_extension=extension,
            )
        except (LocalMessageChannelError, ValueError) as error:
            raise InvalidRequestError("Workflow Trigger descriptor identity 已失效") from error

    def close(self) -> None:
        """关闭 client view。"""

        self._mailbox.close(deadline_ns=monotonic_ns() + 1_000_000_000)

    def __enter__(self) -> WorkflowTriggerMailboxClient:
        """返回 client context。"""

        return self

    def __exit__(self, *_args: object) -> None:
        """退出时关闭 view。"""

        self.close()

    def _snapshot(self, identity: WorkflowTriggerDescriptorIdentity):
        """读取 snapshot 并统一映射 owner fence。"""

        try:
            return self._mailbox.try_read_response_snapshot(
                _to_transport_identity(identity)
            )
        except LocalMessageChannelError as error:
            raise InvalidRequestError(str(error)) from error

    def _read_active_extension(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> bytes:
        """读取 client 自有 descriptor extension。"""

        try:
            return self._mailbox.read_descriptor_extension(
                _to_transport_identity(identity)
            )
        except LocalMessageChannelError as error:
            raise InvalidRequestError(
                "Workflow Trigger descriptor identity 不匹配"
            ) from error

    @staticmethod
    def _encode(*, schema_id: str, payload: bytes, request_id: UUID) -> bytes:
        """编码并统一映射 JSON 错误。"""

        try:
            return encode_trigger_payload(
                schema_id=schema_id,
                payload=payload,
                request_id=request_id,
            )
        except ChannelInvalidMessageError as error:
            raise InvalidRequestError(str(error)) from error

    @staticmethod
    def _decode(
        wire_bytes: bytes,
        *,
        expected_schema_id: str,
        request_id: UUID,
    ) -> bytes:
        """解码并统一映射 envelope 错误。"""

        try:
            return decode_trigger_payload(
                wire_bytes,
                expected_schema_id=expected_schema_id,
                request_id=request_id,
            )
        except ChannelInvalidMessageError as error:
            raise InvalidRequestError(str(error)) from error

    @staticmethod
    def _raise_transport_error(error_code: int) -> None:
        """把 PREPARE transport 错误映射为现有 SDK 可观察异常。"""

        if error_code != MAILBOX_ERROR_NONE:
            raise InvalidRequestError(
                f"Workflow Trigger transport error: {_business_error_from_transport(error_code)}"
            )


def _business_error_from_transport(error_code: int) -> int:
    """把通用 transport 终态映射为 Trigger 业务错误码。"""

    return {
        MAILBOX_ERROR_DEADLINE_EXCEEDED: contract.ERROR_CODE_DEADLINE_EXCEEDED,
        MAILBOX_ERROR_CANCELLED: contract.ERROR_CODE_CANCELLED,
        MAILBOX_ERROR_INVALID_MESSAGE: contract.ERROR_CODE_CHECKSUM_MISMATCH,
        MAILBOX_ERROR_CAPACITY_EXHAUSTED: (
            contract.ERROR_CODE_TRIGGER_RESPONSE_CAPACITY_EXHAUSTED
        ),
        MAILBOX_ERROR_SERVER_FAILURE: contract.ERROR_CODE_PROTOCOL_ERROR,
    }.get(error_code, contract.ERROR_CODE_PROTOCOL_ERROR)


__all__ = [
    "DESCRIPTOR_STRIDE_BYTES",
    "MAILBOX_FILE_SIZE_BYTES",
    "WorkflowTriggerDescriptorIdentity",
    "WorkflowTriggerMailboxAllocation",
    "WorkflowTriggerMailboxClient",
    "WorkflowTriggerMailboxPrepare",
    "WorkflowTriggerMailboxRequest",
    "WorkflowTriggerMailboxResponse",
    "WorkflowTriggerMailboxServer",
]
