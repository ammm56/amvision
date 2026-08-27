"""未接业务 composition root 的 LocalMessage RPC mailbox v1 engine。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from enum import StrEnum
import mmap
import struct
from threading import Lock
from time import monotonic_ns, sleep
from typing import BinaryIO
from uuid import UUID, uuid4
import zlib

from backend.contracts.ipc.local_message_profiles import RpcChannelProfile
from backend.service.application.message_channels.errors import (
    ChannelCancelledError,
    ChannelCapacityExhaustedError,
    ChannelClosedError,
    ChannelCorruptMessageError,
    ChannelDeadlineExceededError,
    ChannelInvalidMessageError,
    ChannelRestartedError,
    LocalMessageChannelError,
)
from backend.service.application.message_channels.models import RpcRequestContext
from backend.service.application.message_channels.ports import CancellationSource
from backend.service.infrastructure.ipc.local_message.common_layout import (
    CHANNEL_KIND_RPC,
    COMMON_HEADER_SIZE,
    FILE_FLAG_CLOSED,
    NO_PAGE_INDEX,
    RPC_DESCRIPTOR_HEADER,
    RPC_DESCRIPTOR_EXTENSION_OFFSET,
    RPC_DESCRIPTOR_EXTENSION_SIZE,
    RPC_DESCRIPTOR_HEADER_SIZE,
    RPC_ERROR_CANCELLED,
    RPC_ERROR_CAPACITY_EXHAUSTED,
    RPC_ERROR_DEADLINE_EXCEEDED,
    RPC_ERROR_INVALID_MESSAGE,
    RPC_ERROR_NONE,
    RPC_ERROR_SERVER_FAILURE,
    RPC_FLAG_ACKED,
    RPC_FLAG_CANCEL_REQUESTED,
    RPC_FLAG_RESPONSE_COMPRESSED,
    RPC_HEADER,
    RPC_PAGE_HEADER,
    RPC_STATE_FREE,
    RPC_STATE_PROCESSING,
    RPC_STATE_REQUEST,
    RPC_STATE_RESPONSE,
    RPC_STATE_WRITING_REQUEST,
    begin_owner_initialization,
    decode_profile_id,
    encode_profile_id,
    finish_owner_initialization,
    pack_common_header,
    rpc_layout,
    unpack_common_header,
)
from backend.service.infrastructure.ipc.local_message.guards import (
    MmapGuardBusyError,
    acquire_owner,
    descriptor_guard,
    release_owner,
)
from backend.service.infrastructure.ipc.local_message.health import RpcChannelHealth
from backend.service.infrastructure.ipc.local_message.page_pool import (
    MmapResponsePagePool,
)
from backend.service.infrastructure.ipc.local_message.paths import (
    LocalMessageChannelPaths,
)
from backend.service.infrastructure.ipc.mmap_primitives import (
    crc32_ieee,
    new_nonzero_u64_token,
    publish_u32,
)


_COMMON_FLAGS_OFFSET = 84
_RESPONSE_COMPRESSION_MAX_RATIO = 0.875


@dataclass(frozen=True, slots=True)
class RpcTransportIdentity:
    """基础设施内部的 descriptor fence。"""

    descriptor_index: int
    generation: int
    owner_epoch: int
    owner_token: int


class RpcTerminalReason(StrEnum):
    """descriptor 被 transport 收敛时的稳定原因。"""

    CANCELLED = "cancelled"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    ACKNOWLEDGED = "acknowledged"
    RESPONSE_ACK_TIMEOUT = "response_ack_timeout"


@dataclass(frozen=True, slots=True)
class RpcTerminalEvent:
    """供业务 adapter 释放外部资源的 descriptor 终态事件。"""

    identity: RpcTransportIdentity
    request_id: UUID
    reason: RpcTerminalReason


@dataclass(frozen=True, slots=True)
class RpcResponseSnapshot:
    """尚未 ACK 的 response 及 descriptor 扩展快照。"""

    wire_bytes: bytes
    error_code: int
    deadline_ns: int
    response_ack_deadline_ns: int
    extension: bytes


class MmapRpcResponseHandle:
    """持有 client 自有 response bytes，并把 ACK 延迟到 close。"""

    def __init__(self, *, wire_bytes: bytes, ack_callback: object) -> None:
        """绑定不可变 bytes 和幂等 ACK callback。"""

        self._wire_bytes = bytes(wire_bytes)
        self._ack_callback = ack_callback
        self._closed = False
        self._lock = Lock()

    @property
    def wire_bytes(self) -> bytes:
        """返回已脱离 mmap 生命周期的响应。"""

        return self._wire_bytes

    def ack(self) -> None:
        """幂等发布 ACK。"""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            callback = self._ack_callback
            self._ack_callback = None
        if callable(callback):
            callback()

    def close(self) -> None:
        """普通结构化响应 close 等价于 ACK。"""

        self.ack()

    def __enter__(self) -> MmapRpcResponseHandle:
        """返回 context-managed handle。"""

        return self

    def __exit__(self, *_args: object) -> None:
        """退出上下文时 ACK。"""

        self.close()


@dataclass(frozen=True, slots=True)
class RpcResponsePublication:
    """描述一次已经完成的 response publication。"""

    compressed: bool
    page_count: int


class MmapRpcMailboxServer:
    """持有单 owner lock 和 response page allocator 的 RPC server。"""

    def __init__(
        self,
        *,
        paths: LocalMessageChannelPaths,
        profile: RpcChannelProfile,
        channel_id: UUID | None = None,
        response_ack_timeout_seconds: float = 30.0,
    ) -> None:
        """创建固定文件，以新 owner epoch 清空所有旧代资源。"""

        if response_ack_timeout_seconds <= 0:
            raise ValueError("response_ack_timeout_seconds 必须大于 0")
        self.paths = paths
        self.profile = profile
        self.layout = rpc_layout(profile)
        self._requested_channel_id = channel_id
        self.channel_id = channel_id or UUID(int=0)
        self.owner_epoch = new_nonzero_u64_token()
        self.response_ack_timeout_ns = int(response_ack_timeout_seconds * 1e9)
        self._owner_lock: BinaryIO | None = None
        self._file: BinaryIO | None = None
        self._view: mmap.mmap | None = None
        self._page_pool: MmapResponsePagePool | None = None
        self._closed = False
        self._poll_cursor = 0
        self._requests_total = 0
        self._responses_total = 0
        self._acknowledgements_total = 0
        self._cancellations_total = 0
        self._deadline_exceeded_total = 0
        self._capacity_rejections_total = 0
        self._terminal_events: deque[RpcTerminalEvent] = deque()
        try:
            self._initialize_files()
        except Exception:
            self._close_handles()
            raise

    def receive(
        self,
        *,
        deadline_ns: int,
        sweep_before_receive: bool = True,
    ) -> RpcRequestContext | None:
        """在 deadline 前 claim 一条 REQUEST，并按调用方所有权执行 sweep。"""

        received = self.receive_with_extension(
            deadline_ns=deadline_ns,
            sweep_before_receive=sweep_before_receive,
        )
        return None if received is None else received[0]

    def receive_with_extension(
        self,
        *,
        deadline_ns: int,
        sweep_before_receive: bool = True,
    ) -> tuple[RpcRequestContext, bytes] | None:
        """在 claim guard 内同时取得 request 与窄协议扩展快照。"""

        if deadline_ns <= 0:
            raise ValueError("deadline_ns 必须大于 0")
        while True:
            if self._closed:
                return None
            if sweep_before_receive:
                self.sweep()
            received = self._claim_one_request()
            if received is not None:
                return received
            now_ns = monotonic_ns()
            if now_ns >= deadline_ns:
                return None
            sleep(min(self.profile.poll_interval_seconds, (deadline_ns - now_ns) / 1e9))

    def publish_response(
        self,
        request: RpcRequestContext,
        *,
        wire_bytes: bytes,
        descriptor_extension: bytes | None = None,
    ) -> None:
        """校验 request fence 后最多发布一次响应。"""

        self.publish_response_with_receipt(
            request,
            wire_bytes=wire_bytes,
            descriptor_extension=descriptor_extension,
        )

    def publish_response_with_receipt(
        self,
        request: RpcRequestContext,
        *,
        wire_bytes: bytes,
        response_ack_deadline_ns: int | None = None,
        descriptor_extension: bytes | None = None,
    ) -> RpcResponsePublication:
        """发布响应并返回实际压缩与 page-chain 使用情况。"""

        identity = self._identity_from_request(request)
        payload = bytes(wire_bytes)
        if len(payload) > self.profile.max_response_bytes:
            self._publish_error(identity, RPC_ERROR_CAPACITY_EXHAUSTED)
            raise ChannelCapacityExhaustedError("RPC response 超过 profile 上限")
        if request.cancelled:
            error_code = (
                RPC_ERROR_DEADLINE_EXCEEDED
                if monotonic_ns() >= request.deadline_ns
                else RPC_ERROR_CANCELLED
            )
            self._publish_error(identity, error_code)
            raise _error_from_code(error_code)
        return self._publish_payload(
            identity=identity,
            payload=payload,
            error_code=RPC_ERROR_NONE,
            response_ack_deadline_ns=response_ack_deadline_ns,
            descriptor_extension=descriptor_extension,
        )

    def publish_response_segments_with_receipt(
        self,
        request: RpcRequestContext,
        *,
        wire_segments: tuple[bytes, ...],
        response_ack_deadline_ns: int | None = None,
        descriptor_extension: bytes | None = None,
    ) -> RpcResponsePublication:
        """不构造大型中间 bytes 地发布逐字节等价的 response 分段。"""

        identity = self._identity_from_request(request)
        segments = tuple(bytes(segment) for segment in wire_segments)
        raw_size = sum(len(segment) for segment in segments)
        if raw_size > self.profile.max_response_bytes:
            self._publish_error(identity, RPC_ERROR_CAPACITY_EXHAUSTED)
            raise ChannelCapacityExhaustedError("RPC response 超过 profile 上限")
        if request.cancelled:
            error_code = (
                RPC_ERROR_DEADLINE_EXCEEDED
                if monotonic_ns() >= request.deadline_ns
                else RPC_ERROR_CANCELLED
            )
            self._publish_error(identity, error_code)
            raise _error_from_code(error_code)
        return self._publish_payload_segments(
            identity=identity,
            segments=segments,
            error_code=RPC_ERROR_NONE,
            response_ack_deadline_ns=response_ack_deadline_ns,
            descriptor_extension=descriptor_extension,
        )

    def publish_failure(self, request: RpcRequestContext) -> None:
        """在 handler 失败时发布稳定 server failure。"""

        self._publish_error(self._identity_from_request(request), RPC_ERROR_SERVER_FAILURE)

    def sweep(
        self,
        *,
        now_ns: int | None = None,
        descriptor_indexes: tuple[int, ...] | None = None,
    ) -> tuple[RpcTerminalEvent, ...]:
        """收敛过期、取消和已 ACK 的 descriptor/page。

        ``now_ns`` 只用于服务端确定性测试；生产调用始终使用
        本进程 ``monotonic_ns``。
        """

        if self._view is None:
            return ()
        events: list[RpcTerminalEvent] = []
        observed_now_ns = monotonic_ns() if now_ns is None else now_ns
        if observed_now_ns <= 0:
            raise ValueError("RPC sweep now_ns 必须大于 0")
        indexes = (
            range(self.profile.descriptor_count)
            if descriptor_indexes is None
            else dict.fromkeys(descriptor_indexes)
        )
        for descriptor_index in indexes:
            if not 0 <= descriptor_index < self.profile.descriptor_count:
                raise ValueError("RPC descriptor_index 超出 profile 范围")
            header = self._read_descriptor(descriptor_index)
            state = header[0]
            if state == RPC_STATE_FREE:
                continue
            flags = int(header[1])
            owner_changed = header[3] != self.owner_epoch
            needs_terminal_transition = owner_changed
            if state in {
                RPC_STATE_WRITING_REQUEST,
                RPC_STATE_REQUEST,
                RPC_STATE_PROCESSING,
            }:
                needs_terminal_transition = needs_terminal_transition or bool(
                    flags & RPC_FLAG_CANCEL_REQUESTED
                    or observed_now_ns >= int(header[6])
                )
            elif state == RPC_STATE_RESPONSE:
                needs_terminal_transition = needs_terminal_transition or bool(
                    flags & (RPC_FLAG_ACKED | RPC_FLAG_CANCEL_REQUESTED)
                    or observed_now_ns >= int(header[15])
                )
            if not needs_terminal_transition:
                continue
            try:
                with descriptor_guard(
                    guard_path=self.paths.guard_path,
                    descriptor_index=descriptor_index,
                    deadline_ns=monotonic_ns() + 2_000_000,
                    poll_interval_seconds=self.profile.poll_interval_seconds,
                ):
                    header = self._read_descriptor(descriptor_index)
                    state = header[0]
                    if state == RPC_STATE_FREE:
                        continue
                    if header[3] != self.owner_epoch:
                        self._reset_descriptor_locked(descriptor_index, header[2])
                        continue
                    flags = header[1]
                    deadline_ns = header[6]
                    identity = RpcTransportIdentity(
                        descriptor_index=descriptor_index,
                        generation=header[2],
                        owner_epoch=header[3],
                        owner_token=header[5],
                    )
                    request_id = UUID(bytes=header[4])
                    if state == RPC_STATE_WRITING_REQUEST and (
                        flags & RPC_FLAG_CANCEL_REQUESTED
                        or observed_now_ns >= deadline_ns
                    ):
                        self._reset_descriptor_locked(descriptor_index, header[2])
                        events.append(
                            RpcTerminalEvent(
                                identity=identity,
                                request_id=request_id,
                                reason=(
                                    RpcTerminalReason.DEADLINE_EXCEEDED
                                    if observed_now_ns >= deadline_ns
                                    else RpcTerminalReason.CANCELLED
                                ),
                            )
                        )
                    elif state in {RPC_STATE_REQUEST, RPC_STATE_PROCESSING} and (
                        flags & RPC_FLAG_CANCEL_REQUESTED
                        or observed_now_ns >= deadline_ns
                    ):
                        code = (
                            RPC_ERROR_DEADLINE_EXCEEDED
                            if observed_now_ns >= deadline_ns
                            else RPC_ERROR_CANCELLED
                        )
                        self._publish_error_locked(identity, code)
                        events.append(
                            RpcTerminalEvent(
                                identity=identity,
                                request_id=request_id,
                                reason=(
                                    RpcTerminalReason.DEADLINE_EXCEEDED
                                    if code == RPC_ERROR_DEADLINE_EXCEEDED
                                    else RpcTerminalReason.CANCELLED
                                ),
                            )
                        )
                    elif state == RPC_STATE_RESPONSE and (
                        flags & RPC_FLAG_ACKED
                        or flags & RPC_FLAG_CANCEL_REQUESTED
                        or observed_now_ns >= header[15]
                    ):
                        if flags & RPC_FLAG_ACKED:
                            self._acknowledgements_total += 1
                            reason = RpcTerminalReason.ACKNOWLEDGED
                        elif flags & RPC_FLAG_CANCEL_REQUESTED:
                            reason = RpcTerminalReason.CANCELLED
                        else:
                            reason = RpcTerminalReason.RESPONSE_ACK_TIMEOUT
                        self._reset_descriptor_locked(descriptor_index, header[2])
                        events.append(
                            RpcTerminalEvent(
                                identity=identity,
                                request_id=request_id,
                                reason=reason,
                            )
                        )
            except MmapGuardBusyError:
                continue
        self._terminal_events.extend(events)
        return tuple(events)

    def drain_terminal_events(self) -> tuple[RpcTerminalEvent, ...]:
        """返回并清空尚未被业务 adapter 消费的终态事件。"""

        events = tuple(self._terminal_events)
        self._terminal_events.clear()
        return events

    def descriptor_statuses(self) -> tuple[tuple[int, bytes], ...]:
        """返回无正文的 transport state 与扩展快照，供 health adapter 汇总。"""

        if self._view is None:
            return ()
        statuses: list[tuple[int, bytes]] = []
        for descriptor_index in range(self.profile.descriptor_count):
            header = self._read_descriptor(descriptor_index)
            start = self._descriptor_offset(descriptor_index) + RPC_DESCRIPTOR_EXTENSION_OFFSET
            statuses.append(
                (
                    int(header[0]),
                    bytes(
                        self._require_view()[
                            start : start + RPC_DESCRIPTOR_EXTENSION_SIZE
                        ]
                    ),
                )
            )
        return tuple(statuses)

    def transport_identity(self, request: RpcRequestContext) -> RpcTransportIdentity:
        """返回已验证的 transport identity，供窄协议扩展建立 fence。"""

        return self._identity_from_request(request)

    def read_processing_extension(
        self,
        request: RpcRequestContext,
        *,
        offset: int = 0,
        size: int = RPC_DESCRIPTOR_EXTENSION_SIZE,
    ) -> bytes:
        """读取仍处于 PROCESSING 的 descriptor 扩展区。"""

        identity = self._identity_from_request(request)
        self._validate_extension_range(offset=offset, size=size)
        with descriptor_guard(
            guard_path=self.paths.guard_path,
            descriptor_index=identity.descriptor_index,
            deadline_ns=monotonic_ns() + 1_000_000_000,
            poll_interval_seconds=self.profile.poll_interval_seconds,
        ):
            self._require_processing_identity_locked(identity)
            start = self._descriptor_offset(identity.descriptor_index) + RPC_DESCRIPTOR_EXTENSION_OFFSET + offset
            return bytes(self._require_view()[start : start + size])

    def write_processing_extension(
        self,
        request: RpcRequestContext,
        *,
        extension: bytes,
        offset: int = 0,
    ) -> None:
        """在发布 response 前更新 descriptor 扩展区。"""

        identity = self._identity_from_request(request)
        payload = bytes(extension)
        self._validate_extension_range(offset=offset, size=len(payload))
        with descriptor_guard(
            guard_path=self.paths.guard_path,
            descriptor_index=identity.descriptor_index,
            deadline_ns=monotonic_ns() + 1_000_000_000,
            poll_interval_seconds=self.profile.poll_interval_seconds,
        ):
            self._require_processing_identity_locked(identity)
            start = self._descriptor_offset(identity.descriptor_index) + RPC_DESCRIPTOR_EXTENSION_OFFSET + offset
            self._require_view()[start : start + len(payload)] = payload

    def update_processing_deadline(
        self,
        request: RpcRequestContext,
        *,
        deadline_ns: int,
        descriptor_extension: bytes | None = None,
    ) -> RpcRequestContext:
        """原子更新 authoritative deadline 和可选窄协议扩展。"""

        if deadline_ns <= monotonic_ns():
            raise ChannelDeadlineExceededError("RPC authoritative deadline 已到期")
        identity = self._identity_from_request(request)
        extension = (
            None if descriptor_extension is None else bytes(descriptor_extension)
        )
        if extension is not None:
            self._validate_extension_range(offset=0, size=len(extension))
        with descriptor_guard(
            guard_path=self.paths.guard_path,
            descriptor_index=identity.descriptor_index,
            deadline_ns=monotonic_ns() + 1_000_000_000,
            poll_interval_seconds=self.profile.poll_interval_seconds,
        ):
            self._require_processing_identity_locked(identity)
            struct.pack_into(
                "<Q",
                self._require_view(),
                self._descriptor_offset(identity.descriptor_index) + 48,
                deadline_ns,
            )
            if extension is not None:
                self._write_descriptor_extension_locked(
                    identity,
                    extension=extension,
                )
        return replace(
            request,
            deadline_ns=deadline_ns,
            _cancel_probe=lambda identity=identity, deadline_ns=deadline_ns: self._is_cancelled(
                identity, deadline_ns
            ),
        )

    def health(self) -> RpcChannelHealth:
        """返回 RPC 专属 descriptor/page 和生命周期指标。"""

        states = [
            self._read_descriptor(index)[0]
            for index in range(self.profile.descriptor_count)
        ]
        page_pool = self._require_page_pool()
        return RpcChannelHealth(
            channel_id=self.channel_id,
            owner_epoch=self.owner_epoch,
            closed=self._closed,
            free_descriptors=states.count(RPC_STATE_FREE),
            request_descriptors=states.count(RPC_STATE_REQUEST),
            processing_descriptors=states.count(RPC_STATE_PROCESSING),
            response_descriptors=states.count(RPC_STATE_RESPONSE),
            free_pages=page_pool.free_page_count(),
            requests_total=self._requests_total,
            responses_total=self._responses_total,
            acknowledgements_total=self._acknowledgements_total,
            cancellations_total=self._cancellations_total,
            deadline_exceeded_total=self._deadline_exceeded_total,
            capacity_rejections_total=self._capacity_rejections_total,
        )

    def close(self, *, deadline_ns: int) -> None:
        """幂等发布 closed fence 并有界回收已 ACK response。"""

        if self._closed:
            return
        self._closed = True
        view = self._view
        if view is not None:
            struct.pack_into("<I", view, _COMMON_FLAGS_OFFSET, FILE_FLAG_CLOSED)
            while monotonic_ns() < deadline_ns:
                if self._reclaim_all_descriptors_for_close(deadline_ns=deadline_ns):
                    break
                sleep(self.profile.poll_interval_seconds)
            view.flush()
        self._close_handles()

    def _reclaim_all_descriptors_for_close(self, *, deadline_ns: int) -> bool:
        """owner fence 发布后，在 descriptor guard 下回收全部旧 epoch 资源。"""

        all_free = True
        for descriptor_index in range(self.profile.descriptor_count):
            header = self._read_descriptor(descriptor_index)
            if header[0] == RPC_STATE_FREE:
                continue
            all_free = False
            now_ns = monotonic_ns()
            if now_ns >= deadline_ns:
                break
            try:
                with descriptor_guard(
                    guard_path=self.paths.guard_path,
                    descriptor_index=descriptor_index,
                    deadline_ns=min(deadline_ns, now_ns + 2_000_000),
                    poll_interval_seconds=self.profile.poll_interval_seconds,
                ):
                    header = self._read_descriptor(descriptor_index)
                    if header[0] != RPC_STATE_FREE:
                        self._reset_descriptor_locked(descriptor_index, header[2])
            except MmapGuardBusyError:
                continue
        return all_free or all(
            self._read_descriptor(index)[0] == RPC_STATE_FREE
            for index in range(self.profile.descriptor_count)
        )

    def _initialize_files(self) -> None:
        """创建固定 mapping、guard 和 owner epoch headers。"""

        self.paths.mmap_path.parent.mkdir(parents=True, exist_ok=True)
        self._owner_lock = acquire_owner(self.paths.owner_lock_path)
        guard_file = self.paths.guard_path.open("a+b", buffering=0)
        try:
            guard_file.truncate(max(self.profile.descriptor_count, 1))
        finally:
            guard_file.close()
        existing_size = (
            self.paths.mmap_path.stat().st_size
            if self.paths.mmap_path.exists()
            else 0
        )
        if existing_size not in {0, self.layout.file_size_bytes}:
            raise ChannelCorruptMessageError("RPC owner 文件长度与冻结 profile 不匹配")
        self._file = self.paths.mmap_path.open("a+b", buffering=0)
        if existing_size == 0:
            self._file.truncate(self.layout.file_size_bytes)
        self._view = mmap.mmap(
            self._file.fileno(), self.layout.file_size_bytes, access=mmap.ACCESS_WRITE
        )
        view = self._require_view()
        current_magic = bytes(view[:8])
        if existing_size == self.layout.file_size_bytes and current_magic == b"AMVLMSG\0":
            existing = unpack_common_header(
                view,
                expected_kind=CHANNEL_KIND_RPC,
                expected_fingerprint=self.layout.fingerprint,
            )
            if (
                self._requested_channel_id is not None
                and existing.channel_id != self._requested_channel_id
            ):
                raise ChannelInvalidMessageError("RPC channel_id 与已有文件不匹配")
            self.channel_id = existing.channel_id
        else:
            self.channel_id = self._requested_channel_id or uuid4()
        packed_common = pack_common_header(
            channel_kind=CHANNEL_KIND_RPC,
            fingerprint=self.layout.fingerprint,
            channel_id=self.channel_id,
            owner_epoch=self.owner_epoch,
        )
        begin_owner_initialization(view, packed_common)
        RPC_HEADER.pack_into(
            view,
            COMMON_HEADER_SIZE,
            self.profile.descriptor_count,
            RPC_DESCRIPTOR_HEADER_SIZE,
            self.layout.descriptor_stride_bytes,
            self.profile.inline_request_capacity_bytes,
            self.profile.inline_response_capacity_bytes,
            RPC_PAGE_HEADER.size,
            self.profile.overflow_page_capacity_bytes,
            self.profile.overflow_page_count,
            self.profile.max_overflow_pages_per_response,
            self.profile.max_request_bytes,
            self.profile.max_response_bytes,
            self.profile.compression_threshold_bytes,
            self.layout.descriptor_region_offset,
            self.layout.page_region_offset,
            self.layout.file_size_bytes,
            int(self.profile.poll_interval_seconds * 1e9),
            encode_profile_id(self.profile.profile_id),
        )
        for descriptor_index in range(self.profile.descriptor_count):
            self._reset_descriptor_locked(descriptor_index, 0)
        self._page_pool = MmapResponsePagePool(
            view=view,
            profile=self.profile,
            layout=self.layout,
            owner_epoch=self.owner_epoch,
        )
        self._page_pool.reset_all()
        finish_owner_initialization(view)
        view.flush()

    def _claim_one_request(self) -> tuple[RpcRequestContext, bytes] | None:
        """公平扫描并 claim 一条已完整发布的 REQUEST。"""

        view = self._require_view()
        for distance in range(self.profile.descriptor_count):
            descriptor_index = (self._poll_cursor + distance) % self.profile.descriptor_count
            if self._read_descriptor(descriptor_index)[0] != RPC_STATE_REQUEST:
                continue
            try:
                with descriptor_guard(
                    guard_path=self.paths.guard_path,
                    descriptor_index=descriptor_index,
                    deadline_ns=monotonic_ns() + 2_000_000,
                    poll_interval_seconds=self.profile.poll_interval_seconds,
                ):
                    header = self._read_descriptor(descriptor_index)
                    if header[0] != RPC_STATE_REQUEST:
                        continue
                    identity = RpcTransportIdentity(
                        descriptor_index=descriptor_index,
                        generation=header[2],
                        owner_epoch=header[3],
                        owner_token=header[5],
                    )
                    if identity.owner_epoch != self.owner_epoch:
                        self._reset_descriptor_locked(descriptor_index, header[2])
                        continue
                    if header[1] & RPC_FLAG_CANCEL_REQUESTED:
                        self._publish_error_locked(identity, RPC_ERROR_CANCELLED)
                        continue
                    if monotonic_ns() >= header[6]:
                        self._publish_error_locked(
                            identity, RPC_ERROR_DEADLINE_EXCEEDED
                        )
                        continue
                    request_size = header[7]
                    if not 0 <= request_size <= self.profile.max_request_bytes:
                        self._publish_error_locked(identity, RPC_ERROR_INVALID_MESSAGE)
                        continue
                    payload_offset = self._request_offset(descriptor_index)
                    payload = bytes(view[payload_offset : payload_offset + request_size])
                    if crc32_ieee(payload) != header[8]:
                        self._publish_error_locked(identity, RPC_ERROR_INVALID_MESSAGE)
                        continue
                    publish_u32(
                        view,
                        offset=self._descriptor_offset(descriptor_index),
                        value=RPC_STATE_PROCESSING,
                    )
                    self._requests_total += 1
                    self._poll_cursor = (descriptor_index + 1) % self.profile.descriptor_count
                    request_id = UUID(bytes=header[4])
                    deadline_ns = header[6]
                    extension_start = (
                        self._descriptor_offset(descriptor_index)
                        + RPC_DESCRIPTOR_EXTENSION_OFFSET
                    )
                    extension = bytes(
                        view[
                            extension_start : extension_start
                            + RPC_DESCRIPTOR_EXTENSION_SIZE
                        ]
                    )
                    return (
                        RpcRequestContext(
                            request_id=request_id,
                            wire_bytes=payload,
                            deadline_ns=deadline_ns,
                            owner_epoch=self.owner_epoch,
                            _cancel_probe=lambda identity=identity, deadline_ns=deadline_ns: self._is_cancelled(
                                identity, deadline_ns
                            ),
                            _transport_token=identity,
                        ),
                        extension,
                    )
            except MmapGuardBusyError:
                continue
        return None

    def _publish_payload(
        self,
        *,
        identity: RpcTransportIdentity,
        payload: bytes,
        error_code: int,
        response_ack_deadline_ns: int | None = None,
        descriptor_extension: bytes | None = None,
    ) -> RpcResponsePublication:
        """压缩可获益响应，写 inline/page，最后发布 RESPONSE state。"""

        return self._publish_payload_segments(
            identity=identity,
            segments=(payload,),
            error_code=error_code,
            response_ack_deadline_ns=response_ack_deadline_ns,
            descriptor_extension=descriptor_extension,
        )

    def _publish_payload_segments(
        self,
        *,
        identity: RpcTransportIdentity,
        segments: tuple[bytes, ...],
        error_code: int,
        response_ack_deadline_ns: int | None = None,
        descriptor_extension: bytes | None = None,
    ) -> RpcResponsePublication:
        """在同一 publication 边界内流式压缩和计算整体 CRC。"""

        extension = (
            None if descriptor_extension is None else bytes(descriptor_extension)
        )
        if extension is not None:
            self._validate_extension_range(offset=0, size=len(extension))
        raw_size = sum(len(segment) for segment in segments)
        raw_crc = 0
        for segment in segments:
            raw_crc = zlib.crc32(segment, raw_crc)
        raw_crc &= 0xFFFFFFFF
        with descriptor_guard(
            guard_path=self.paths.guard_path,
            descriptor_index=identity.descriptor_index,
            deadline_ns=monotonic_ns() + 1_000_000_000,
            poll_interval_seconds=self.profile.poll_interval_seconds,
        ):
            header = self._require_processing_identity_locked(identity)
            if header[1] & RPC_FLAG_CANCEL_REQUESTED:
                self._publish_error_locked(identity, RPC_ERROR_CANCELLED)
                raise ChannelCancelledError("RPC request 已取消")
            if monotonic_ns() >= header[6]:
                self._publish_error_locked(identity, RPC_ERROR_DEADLINE_EXCEEDED)
                raise ChannelDeadlineExceededError("RPC request 已超时")
            if extension is not None:
                self._write_descriptor_extension_locked(
                    identity,
                    extension=extension,
                )
            stored_payload, compressed = self._compress_response_segments(
                segments,
                raw_size=raw_size,
            )
            first_page = NO_PAGE_INDEX
            page_count = 0
            flags = header[1] & RPC_FLAG_CANCEL_REQUESTED
            if compressed:
                flags |= RPC_FLAG_RESPONSE_COMPRESSED
            try:
                if len(stored_payload) <= self.profile.inline_response_capacity_bytes:
                    response_offset = self._response_offset(identity.descriptor_index)
                    view = self._require_view()
                    view[response_offset : response_offset + len(stored_payload)] = stored_payload
                else:
                    first_page, page_count = self._require_page_pool().reserve_write_publish(
                        descriptor_index=identity.descriptor_index,
                        descriptor_generation=identity.generation,
                        payload=stored_payload,
                    )
                self._write_response_header_locked(
                    identity=identity,
                    previous=header,
                    flags=flags,
                    raw_size=raw_size,
                    raw_crc=raw_crc,
                    stored_size=len(stored_payload),
                    first_page=first_page,
                    page_count=page_count,
                    error_code=error_code,
                    response_ack_deadline_ns=response_ack_deadline_ns,
                )
            except ChannelCapacityExhaustedError:
                self._require_page_pool().free_for_descriptor(
                    descriptor_index=identity.descriptor_index,
                    descriptor_generation=identity.generation,
                )
                self._write_response_header_locked(
                    identity=identity,
                    previous=header,
                    flags=header[1] & RPC_FLAG_CANCEL_REQUESTED,
                    raw_size=0,
                    raw_crc=0,
                    stored_size=0,
                    first_page=NO_PAGE_INDEX,
                    page_count=0,
                    error_code=RPC_ERROR_CAPACITY_EXHAUSTED,
                    response_ack_deadline_ns=None,
                )
                self._capacity_rejections_total += 1
                self._responses_total += 1
                raise
            except Exception:
                self._require_page_pool().free_for_descriptor(
                    descriptor_index=identity.descriptor_index,
                    descriptor_generation=identity.generation,
                )
                raise
            self._responses_total += 1
            return RpcResponsePublication(
                compressed=compressed,
                page_count=page_count,
            )

    def _publish_error(self, identity: RpcTransportIdentity, error_code: int) -> None:
        """取得 descriptor guard 后发布稳定空正文错误。"""

        with descriptor_guard(
            guard_path=self.paths.guard_path,
            descriptor_index=identity.descriptor_index,
            deadline_ns=monotonic_ns() + 1_000_000_000,
            poll_interval_seconds=self.profile.poll_interval_seconds,
        ):
            self._publish_error_locked(identity, error_code)

    def _publish_error_locked(
        self, identity: RpcTransportIdentity, error_code: int
    ) -> None:
        """在已持有 guard 时发布错误 RESPONSE。"""

        header = self._read_descriptor(identity.descriptor_index)
        if not self._identity_matches(header, identity):
            raise ChannelRestartedError("RPC descriptor identity 已变化")
        if header[0] == RPC_STATE_RESPONSE:
            return
        if header[0] not in {RPC_STATE_REQUEST, RPC_STATE_PROCESSING}:
            raise ChannelInvalidMessageError("RPC descriptor 不可发布响应")
        self._write_response_header_locked(
            identity=identity,
            previous=header,
            flags=header[1] & RPC_FLAG_CANCEL_REQUESTED,
            raw_size=0,
            raw_crc=0,
            stored_size=0,
            first_page=NO_PAGE_INDEX,
            page_count=0,
            error_code=error_code,
            response_ack_deadline_ns=None,
        )
        if error_code == RPC_ERROR_CANCELLED:
            self._cancellations_total += 1
        elif error_code == RPC_ERROR_DEADLINE_EXCEEDED:
            self._deadline_exceeded_total += 1
        elif error_code == RPC_ERROR_CAPACITY_EXHAUSTED:
            self._capacity_rejections_total += 1
        self._responses_total += 1

    def _write_response_header_locked(
        self,
        *,
        identity: RpcTransportIdentity,
        previous: tuple[object, ...],
        flags: int,
        raw_size: int,
        raw_crc: int,
        stored_size: int,
        first_page: int,
        page_count: int,
        error_code: int,
        response_ack_deadline_ns: int | None,
    ) -> None:
        """写 response metadata，并把 state 作为最后 publication 字段。"""

        now_ns = monotonic_ns()
        resolved_ack_deadline_ns = (
            response_ack_deadline_ns
            if response_ack_deadline_ns is not None
            else now_ns + self.response_ack_timeout_ns
        )
        if resolved_ack_deadline_ns <= now_ns:
            raise ChannelDeadlineExceededError("RPC response ACK deadline 已到期")
        descriptor_offset = self._descriptor_offset(identity.descriptor_index)
        extension = bytes(
            self._require_view()[
                descriptor_offset + RPC_DESCRIPTOR_EXTENSION_OFFSET :
                descriptor_offset + RPC_DESCRIPTOR_HEADER_SIZE
            ]
        )
        RPC_DESCRIPTOR_HEADER.pack_into(
            self._require_view(),
            descriptor_offset,
            RPC_STATE_PROCESSING,
            flags,
            identity.generation,
            identity.owner_epoch,
            previous[4],
            identity.owner_token,
            previous[6],
            previous[7],
            previous[8],
            raw_size,
            raw_crc,
            first_page,
            page_count,
            error_code,
            stored_size,
            resolved_ack_deadline_ns,
            now_ns,
        )
        self._require_view()[
            descriptor_offset + RPC_DESCRIPTOR_EXTENSION_OFFSET :
            descriptor_offset + RPC_DESCRIPTOR_HEADER_SIZE
        ] = extension
        publish_u32(
            self._require_view(),
            offset=descriptor_offset,
            value=RPC_STATE_RESPONSE,
        )

    def _reset_descriptor_locked(self, descriptor_index: int, generation: int) -> None:
        """回收该 descriptor 的所有 owner pages 并保留 generation fence。"""

        if self._page_pool is not None:
            self._page_pool.free_for_descriptor(
                descriptor_index=descriptor_index,
                descriptor_generation=generation,
            )
        RPC_DESCRIPTOR_HEADER.pack_into(
            self._require_view(),
            self._descriptor_offset(descriptor_index),
            RPC_STATE_FREE,
            0,
            generation,
            self.owner_epoch,
            b"\0" * 16,
            0,
            0,
            0,
            0,
            0,
            0,
            NO_PAGE_INDEX,
            0,
            0,
            0,
            0,
            0,
        )

    def _is_cancelled(self, identity: RpcTransportIdentity, deadline_ns: int) -> bool:
        """无锁观察取消、deadline 和 owner fence。"""

        if self._closed or monotonic_ns() >= deadline_ns:
            return True
        try:
            header = self._read_descriptor(identity.descriptor_index)
        except (ValueError, BufferError):
            return True
        return not self._identity_matches(header, identity) or bool(
            header[1] & RPC_FLAG_CANCEL_REQUESTED
        )

    def _identity_from_request(
        self, request: RpcRequestContext
    ) -> RpcTransportIdentity:
        """从 opaque token 恢复基础设施 identity。"""

        identity = request._transport_token
        if not isinstance(identity, RpcTransportIdentity):
            raise ChannelInvalidMessageError("RpcRequestContext 不属于该 transport")
        if request.owner_epoch != self.owner_epoch:
            raise ChannelRestartedError("RPC owner epoch 已变化")
        return identity

    def _require_processing_identity_locked(
        self, identity: RpcTransportIdentity
    ) -> tuple[object, ...]:
        """要求 descriptor 仍属于该 handler 且处于 PROCESSING。"""

        header = self._read_descriptor(identity.descriptor_index)
        if not self._identity_matches(header, identity):
            raise ChannelRestartedError("RPC descriptor identity 已变化")
        if header[0] != RPC_STATE_PROCESSING:
            raise ChannelInvalidMessageError("RPC request 已经进入终态")
        return header

    def _identity_matches(
        self, header: tuple[object, ...], identity: RpcTransportIdentity
    ) -> bool:
        """比较 generation、epoch 和 owner token。"""

        return (
            header[2] == identity.generation
            and header[3] == identity.owner_epoch
            and header[5] == identity.owner_token
        )

    def _compress_response(self, payload: bytes) -> tuple[bytes, bool]:
        """只在达到阈值且至少节省 12.5% 时保留 zlib 结果。"""

        return self._compress_response_segments((payload,), raw_size=len(payload))

    def _compress_response_segments(
        self,
        segments: tuple[bytes, ...],
        *,
        raw_size: int,
    ) -> tuple[bytes, bool]:
        """不合并原始分段地完成 level-1 压缩判定。"""

        if raw_size < self.profile.compression_threshold_bytes:
            return b"".join(segments), False
        # LocalMessage 是低延迟热路径；level=1 与迁移前 Trigger 契约一致，
        # 避免为了少数 page 容量牺牲大 JSON 的 CPU 和尾延迟。
        compressor = zlib.compressobj(level=1)
        compressed_parts = [compressor.compress(segment) for segment in segments]
        compressed_parts.append(compressor.flush())
        compressed = b"".join(part for part in compressed_parts if part)
        if len(compressed) <= int(raw_size * _RESPONSE_COMPRESSION_MAX_RATIO):
            return compressed, True
        return b"".join(segments), False

    def _read_descriptor(self, descriptor_index: int) -> tuple[object, ...]:
        """读取 descriptor header。"""

        return RPC_DESCRIPTOR_HEADER.unpack_from(
            self._require_view(), self._descriptor_offset(descriptor_index)
        )

    def _write_descriptor_extension_locked(
        self,
        identity: RpcTransportIdentity,
        *,
        extension: bytes,
    ) -> None:
        """在 server 已持有 guard 时覆盖完整窄协议扩展区。"""

        payload = bytes(extension)
        self._validate_extension_range(offset=0, size=len(payload))
        start = (
            self._descriptor_offset(identity.descriptor_index)
            + RPC_DESCRIPTOR_EXTENSION_OFFSET
        )
        self._require_view()[start : start + RPC_DESCRIPTOR_EXTENSION_SIZE] = (
            payload.ljust(RPC_DESCRIPTOR_EXTENSION_SIZE, b"\0")
        )

    @staticmethod
    def _validate_extension_range(*, offset: int, size: int) -> None:
        """限制窄协议只能访问 descriptor 的保留扩展区。"""

        if offset < 0 or size < 0 or offset + size > RPC_DESCRIPTOR_EXTENSION_SIZE:
            raise ValueError("RPC descriptor extension 范围越界")

    def _descriptor_offset(self, descriptor_index: int) -> int:
        """返回 descriptor header offset。"""

        return (
            self.layout.descriptor_region_offset
            + descriptor_index * self.layout.descriptor_stride_bytes
        )

    def _request_offset(self, descriptor_index: int) -> int:
        """返回 descriptor inline request offset。"""

        return self._descriptor_offset(descriptor_index) + RPC_DESCRIPTOR_HEADER_SIZE

    def _response_offset(self, descriptor_index: int) -> int:
        """返回 descriptor inline response offset。"""

        return self._request_offset(descriptor_index) + self.profile.inline_request_capacity_bytes

    def _require_view(self) -> mmap.mmap:
        """返回活动 owner view。"""

        if self._view is None:
            raise ChannelClosedError("RPC server 已关闭")
        return self._view

    def _require_page_pool(self) -> MmapResponsePagePool:
        """返回活动 page pool。"""

        if self._page_pool is None:
            raise ChannelClosedError("RPC server page pool 已关闭")
        return self._page_pool

    def _close_handles(self) -> None:
        """按 view、file、owner lock 顺序幂等关闭资源。"""

        view, file, owner = self._view, self._file, self._owner_lock
        self._view = None
        self._file = None
        self._owner_lock = None
        self._page_pool = None
        if view is not None:
            view.close()
        if file is not None:
            file.close()
        if owner is not None:
            release_owner(owner)


class MmapRpcMailboxClient:
    """验证 header/profile 后使用 descriptor guard 的同步 RPC client。"""

    def __init__(
        self,
        *,
        paths: LocalMessageChannelPaths,
        profile: RpcChannelProfile,
    ) -> None:
        """打开现有 owner 文件，不创建或修改正式容量。"""

        self.paths = paths
        self.profile = profile
        self.layout = rpc_layout(profile)
        self._file: BinaryIO | None = None
        self._view: mmap.mmap | None = None
        self._closed = False
        try:
            self._file = paths.mmap_path.open("r+b", buffering=0)
            if self.paths.mmap_path.stat().st_size != self.layout.file_size_bytes:
                raise ChannelCorruptMessageError("RPC mmap 文件长度不匹配")
            self._view = mmap.mmap(
                self._file.fileno(), self.layout.file_size_bytes, access=mmap.ACCESS_WRITE
            )
            common = unpack_common_header(
                self._view,
                expected_kind=CHANNEL_KIND_RPC,
                expected_fingerprint=self.layout.fingerprint,
            )
            self.channel_id = common.channel_id
            self.owner_epoch = common.owner_epoch
            if common.flags & FILE_FLAG_CLOSED:
                raise ChannelClosedError("RPC owner 已关闭")
            self._validate_rpc_header()
            self._page_reader = MmapResponsePagePool(
                view=self._view,
                profile=self.profile,
                layout=self.layout,
                owner_epoch=self.owner_epoch,
            )
        except FileNotFoundError as error:
            self._close_handles()
            raise ChannelClosedError("RPC owner 文件不存在") from error
        except Exception:
            self._close_handles()
            raise

    def call(
        self,
        *,
        request_id: UUID,
        wire_bytes: bytes,
        deadline_ns: int,
        cancellation: CancellationSource | None = None,
    ) -> MmapRpcResponseHandle:
        """立即 claim descriptor，等待 response 并返回 client-owned bytes。"""

        if self._closed:
            raise ChannelClosedError("RPC client 已关闭")
        if monotonic_ns() >= deadline_ns:
            raise ChannelDeadlineExceededError("RPC deadline 已到期")
        payload = bytes(wire_bytes)
        if len(payload) > self.profile.max_request_bytes:
            raise ChannelInvalidMessageError("RPC request 超过 profile 上限")
        identity = self._claim_descriptor(
            request_id=request_id,
            payload=payload,
            deadline_ns=deadline_ns,
        )
        while True:
            if cancellation is not None and cancellation.is_cancelled():
                self._request_cancel(identity)
                raise ChannelCancelledError("RPC client 已取消")
            now_ns = monotonic_ns()
            if now_ns >= deadline_ns:
                self._request_cancel(identity)
                raise ChannelDeadlineExceededError("RPC response 等待超时")
            self._verify_owner_epoch()
            header = self._read_descriptor(identity.descriptor_index)
            if header[0] == RPC_STATE_RESPONSE:
                snapshot = self.try_read_response_snapshot(identity)
                if snapshot is not None:
                    handle = MmapRpcResponseHandle(
                        wire_bytes=snapshot.wire_bytes,
                        ack_callback=lambda identity=identity: self._ack(identity),
                    )
                    if snapshot.error_code != RPC_ERROR_NONE:
                        handle.ack()
                        raise _error_from_code(snapshot.error_code)
                    return handle
            sleep(self.profile.poll_interval_seconds)

    def close(self, *, deadline_ns: int) -> None:
        """幂等关闭本 client view；不改变 owner 生命周期。"""

        del deadline_ns
        if self._closed:
            return
        self._closed = True
        self._close_handles()

    def claim_prepared(
        self,
        *,
        request_id: UUID,
        wire_bytes: bytes,
        claim_deadline_ns: int,
        descriptor_extension: bytes,
    ) -> RpcTransportIdentity:
        """提交由 server 接受相对 timeout 的两阶段 PREPARE。"""

        if self._closed:
            raise ChannelClosedError("RPC client 已关闭")
        if monotonic_ns() >= claim_deadline_ns:
            raise ChannelDeadlineExceededError("RPC PREPARE claim deadline 已到期")
        payload = bytes(wire_bytes)
        if len(payload) > self.profile.max_request_bytes:
            raise ChannelInvalidMessageError("RPC PREPARE 超过 profile 上限")
        return self._claim_descriptor(
            request_id=request_id,
            payload=payload,
            deadline_ns=(1 << 64) - 1,
            guard_deadline_ns=claim_deadline_ns,
            descriptor_extension=descriptor_extension,
        )

    def try_read_response_snapshot(
        self,
        identity: RpcTransportIdentity,
    ) -> RpcResponseSnapshot | None:
        """在 publication 快速检查后受 guard 保护地复制 response。"""

        self._verify_owner_epoch()
        header = self._read_descriptor(identity.descriptor_index)
        if (
            header[0] != RPC_STATE_RESPONSE
            and self._identity_matches(header, identity)
        ):
            return None
        with descriptor_guard(
            guard_path=self.paths.guard_path,
            descriptor_index=identity.descriptor_index,
            deadline_ns=monotonic_ns() + 1_000_000_000,
            poll_interval_seconds=self.profile.poll_interval_seconds,
        ):
            self._verify_owner_epoch()
            header = self._read_descriptor(identity.descriptor_index)
            if not self._identity_matches(header, identity):
                raise ChannelRestartedError("RPC descriptor 已被 owner fence")
            if header[0] != RPC_STATE_RESPONSE:
                return None
            return RpcResponseSnapshot(
                wire_bytes=self._read_response(identity, header),
                error_code=int(header[13]),
                deadline_ns=int(header[6]),
                response_ack_deadline_ns=int(header[15]),
                extension=self._read_descriptor_extension(identity),
            )

    def reopen_response_for_request(
        self,
        identity: RpcTransportIdentity,
        *,
        descriptor_extension: bytes,
    ) -> None:
        """把 inline PREPARE response 原子转回 WRITING_REQUEST。"""

        extension = bytes(descriptor_extension)
        self._validate_extension_range(offset=0, size=len(extension))
        with descriptor_guard(
            guard_path=self.paths.guard_path,
            descriptor_index=identity.descriptor_index,
            deadline_ns=monotonic_ns() + 1_000_000_000,
            poll_interval_seconds=self.profile.poll_interval_seconds,
        ):
            self._verify_owner_epoch()
            header = self._read_descriptor(identity.descriptor_index)
            if not self._identity_matches(header, identity):
                raise ChannelRestartedError("RPC descriptor 已被 owner fence")
            if header[0] != RPC_STATE_RESPONSE or header[13] != RPC_ERROR_NONE:
                raise ChannelInvalidMessageError("RPC PREPARE response 不可复用")
            if header[12] != 0:
                raise ChannelInvalidMessageError("RPC PREPARE response 必须使用 inline")
            descriptor_offset = self._descriptor_offset(identity.descriptor_index)
            RPC_DESCRIPTOR_HEADER.pack_into(
                self._require_view(),
                descriptor_offset,
                RPC_STATE_WRITING_REQUEST,
                0,
                identity.generation,
                identity.owner_epoch,
                header[4],
                identity.owner_token,
                header[6],
                0,
                0,
                0,
                0,
                NO_PAGE_INDEX,
                0,
                0,
                0,
                0,
                monotonic_ns(),
            )
            self._write_descriptor_extension_locked(
                identity,
                extension=extension,
            )

    def publish_reopened_request(
        self,
        identity: RpcTransportIdentity,
        *,
        wire_bytes: bytes,
        descriptor_extension: bytes,
    ) -> None:
        """写完最终请求后，以 state 为最后字段发布 REQUEST。"""

        payload = bytes(wire_bytes)
        extension = bytes(descriptor_extension)
        if len(payload) > self.profile.max_request_bytes:
            raise ChannelInvalidMessageError("RPC request 超过 profile 上限")
        self._validate_extension_range(offset=0, size=len(extension))
        with descriptor_guard(
            guard_path=self.paths.guard_path,
            descriptor_index=identity.descriptor_index,
            deadline_ns=monotonic_ns() + 1_000_000_000,
            poll_interval_seconds=self.profile.poll_interval_seconds,
        ):
            self._verify_owner_epoch()
            header = self._read_descriptor(identity.descriptor_index)
            if not self._identity_matches(header, identity):
                raise ChannelRestartedError("RPC descriptor 已被 owner fence")
            if header[0] != RPC_STATE_WRITING_REQUEST:
                raise ChannelInvalidMessageError("RPC descriptor 不处于 WRITING_REQUEST")
            if header[1] & RPC_FLAG_CANCEL_REQUESTED:
                raise ChannelCancelledError("RPC request 已取消")
            if monotonic_ns() >= header[6]:
                raise ChannelDeadlineExceededError("RPC request deadline 已到期")
            descriptor_offset = self._descriptor_offset(identity.descriptor_index)
            RPC_DESCRIPTOR_HEADER.pack_into(
                self._require_view(),
                descriptor_offset,
                RPC_STATE_WRITING_REQUEST,
                0,
                identity.generation,
                identity.owner_epoch,
                header[4],
                identity.owner_token,
                header[6],
                len(payload),
                crc32_ieee(payload),
                0,
                0,
                NO_PAGE_INDEX,
                0,
                0,
                0,
                0,
                monotonic_ns(),
            )
            request_offset = descriptor_offset + RPC_DESCRIPTOR_HEADER_SIZE
            self._require_view()[request_offset : request_offset + len(payload)] = payload
            self._write_descriptor_extension_locked(
                identity,
                extension=extension,
            )
            publish_u32(
                self._require_view(),
                offset=descriptor_offset,
                value=RPC_STATE_REQUEST,
            )

    def request_cancel(
        self,
        identity: RpcTransportIdentity,
        *,
        descriptor_extension: bytes | None = None,
    ) -> None:
        """公开幂等取消入口，供两阶段 adapter 使用。"""

        self._request_cancel(identity, descriptor_extension=descriptor_extension)

    def read_descriptor_extension(self, identity: RpcTransportIdentity) -> bytes:
        """在 descriptor guard 内校验 fence 并返回扩展快照。"""

        with descriptor_guard(
            guard_path=self.paths.guard_path,
            descriptor_index=identity.descriptor_index,
            deadline_ns=monotonic_ns() + 1_000_000_000,
            poll_interval_seconds=self.profile.poll_interval_seconds,
        ):
            self._verify_owner_epoch()
            header = self._read_descriptor(identity.descriptor_index)
            if not self._identity_matches(header, identity):
                raise ChannelRestartedError("RPC descriptor 已被 owner fence")
            if header[0] == RPC_STATE_FREE:
                raise ChannelInvalidMessageError("RPC descriptor 已释放")
            return self._read_descriptor_extension(identity)

    def acknowledge(self, identity: RpcTransportIdentity) -> None:
        """公开幂等 ACK 入口，供延迟释放 response 的 adapter 使用。"""

        self._ack(identity)

    def _claim_descriptor(
        self,
        *,
        request_id: UUID,
        payload: bytes,
        deadline_ns: int,
        guard_deadline_ns: int | None = None,
        descriptor_extension: bytes = b"",
    ) -> RpcTransportIdentity:
        """单次扫描 FREE descriptors；满载立即失败且不排队。"""

        extension = bytes(descriptor_extension)
        self._validate_extension_range(offset=0, size=len(extension))
        guard_deadline = guard_deadline_ns or deadline_ns
        for descriptor_index in range(self.profile.descriptor_count):
            if self._read_descriptor(descriptor_index)[0] != RPC_STATE_FREE:
                continue
            try:
                with descriptor_guard(
                    guard_path=self.paths.guard_path,
                    descriptor_index=descriptor_index,
                    deadline_ns=min(guard_deadline, monotonic_ns() + 2_000_000),
                    poll_interval_seconds=self.profile.poll_interval_seconds,
                ):
                    self._verify_owner_epoch()
                    header = self._read_descriptor(descriptor_index)
                    if header[0] != RPC_STATE_FREE:
                        continue
                    generation = (int(header[2]) + 1) & ((1 << 64) - 1)
                    if generation == 0:
                        generation = 1
                    owner_token = new_nonzero_u64_token()
                    identity = RpcTransportIdentity(
                        descriptor_index=descriptor_index,
                        generation=generation,
                        owner_epoch=self.owner_epoch,
                        owner_token=owner_token,
                    )
                    descriptor_offset = self._descriptor_offset(descriptor_index)
                    RPC_DESCRIPTOR_HEADER.pack_into(
                        self._require_view(),
                        descriptor_offset,
                        RPC_STATE_WRITING_REQUEST,
                        0,
                        generation,
                        self.owner_epoch,
                        request_id.bytes,
                        owner_token,
                        deadline_ns,
                        len(payload),
                        crc32_ieee(payload),
                        0,
                        0,
                        NO_PAGE_INDEX,
                        0,
                        0,
                        0,
                        0,
                        monotonic_ns(),
                    )
                    request_offset = descriptor_offset + RPC_DESCRIPTOR_HEADER_SIZE
                    self._require_view()[
                        request_offset : request_offset + len(payload)
                    ] = payload
                    self._write_descriptor_extension_locked(
                        identity,
                        extension=extension,
                    )
                    publish_u32(
                        self._require_view(),
                        offset=descriptor_offset,
                        value=RPC_STATE_REQUEST,
                    )
                    return identity
            except MmapGuardBusyError:
                continue
        raise ChannelCapacityExhaustedError("RPC descriptor 容量已满")

    def _read_response(
        self, identity: RpcTransportIdentity, header: tuple[object, ...]
    ) -> bytes:
        """读取 inline/page 响应，解压并校验原始 CRC。"""

        raw_size = int(header[9])
        raw_crc = int(header[10])
        first_page = int(header[11])
        page_count = int(header[12])
        stored_size = int(header[14])
        if raw_size > self.profile.max_response_bytes or stored_size > self.profile.max_response_bytes:
            raise ChannelCorruptMessageError("RPC response size 超出 profile")
        if page_count == 0:
            if first_page != NO_PAGE_INDEX or stored_size > self.profile.inline_response_capacity_bytes:
                raise ChannelCorruptMessageError("RPC inline response metadata 不合法")
            response_offset = self._response_offset(identity.descriptor_index)
            stored = bytes(
                self._require_view()[response_offset : response_offset + stored_size]
            )
        else:
            stored = self._page_reader.read_published(
                first_page_index=first_page,
                page_count=page_count,
                descriptor_index=identity.descriptor_index,
                descriptor_generation=identity.generation,
                expected_size=stored_size,
            )
        if header[1] & RPC_FLAG_RESPONSE_COMPRESSED:
            try:
                payload = zlib.decompress(stored)
            except zlib.error as error:
                raise ChannelCorruptMessageError("RPC response 压缩正文损坏") from error
        else:
            payload = stored
        if len(payload) != raw_size or crc32_ieee(payload) != raw_crc:
            raise ChannelCorruptMessageError("RPC response 总长度或 CRC 不匹配")
        return payload

    def _request_cancel(
        self,
        identity: RpcTransportIdentity,
        *,
        descriptor_extension: bytes | None = None,
    ) -> None:
        """按 descriptor fence 幂等发布 cancel flag。"""

        try:
            with descriptor_guard(
                guard_path=self.paths.guard_path,
                descriptor_index=identity.descriptor_index,
                deadline_ns=monotonic_ns() + 10_000_000,
                poll_interval_seconds=self.profile.poll_interval_seconds,
            ):
                header = self._read_descriptor(identity.descriptor_index)
                if self._identity_matches(header, identity) and header[0] in {
                    RPC_STATE_WRITING_REQUEST,
                    RPC_STATE_REQUEST,
                    RPC_STATE_PROCESSING,
                    RPC_STATE_RESPONSE,
                }:
                    if descriptor_extension is not None:
                        self._write_descriptor_extension_locked(
                            identity,
                            extension=descriptor_extension,
                        )
                    struct.pack_into(
                        "<I",
                        self._require_view(),
                        self._descriptor_offset(identity.descriptor_index) + 4,
                        int(header[1]) | RPC_FLAG_CANCEL_REQUESTED,
                    )
        except (MmapGuardBusyError, LocalMessageChannelError, ValueError):
            return

    def _ack(self, identity: RpcTransportIdentity) -> None:
        """按 identity 发布 ACK；owner 已重启时安全 no-op。"""

        if self._closed:
            return
        try:
            with descriptor_guard(
                guard_path=self.paths.guard_path,
                descriptor_index=identity.descriptor_index,
                deadline_ns=monotonic_ns() + 1_000_000_000,
                poll_interval_seconds=self.profile.poll_interval_seconds,
            ):
                header = self._read_descriptor(identity.descriptor_index)
                if self._identity_matches(header, identity) and header[0] == RPC_STATE_RESPONSE:
                    struct.pack_into(
                        "<I",
                        self._require_view(),
                        self._descriptor_offset(identity.descriptor_index) + 4,
                        int(header[1]) | RPC_FLAG_ACKED,
                    )
        except (MmapGuardBusyError, LocalMessageChannelError, ValueError, BufferError):
            return

    def _validate_rpc_header(self) -> None:
        """逐字段验证 profile header，拒绝静默容量漂移。"""

        values = RPC_HEADER.unpack_from(self._require_view(), COMMON_HEADER_SIZE)
        expected = (
            self.profile.descriptor_count,
            RPC_DESCRIPTOR_HEADER_SIZE,
            self.layout.descriptor_stride_bytes,
            self.profile.inline_request_capacity_bytes,
            self.profile.inline_response_capacity_bytes,
            RPC_PAGE_HEADER.size,
            self.profile.overflow_page_capacity_bytes,
            self.profile.overflow_page_count,
            self.profile.max_overflow_pages_per_response,
            self.profile.max_request_bytes,
            self.profile.max_response_bytes,
            self.profile.compression_threshold_bytes,
            self.layout.descriptor_region_offset,
            self.layout.page_region_offset,
            self.layout.file_size_bytes,
            int(self.profile.poll_interval_seconds * 1e9),
        )
        if values[:16] != expected:
            raise ChannelCorruptMessageError("RPC profile header 不匹配")
        if decode_profile_id(values[16]) != self.profile.profile_id:
            raise ChannelCorruptMessageError("RPC profile_id 不匹配")

    def _verify_owner_epoch(self) -> None:
        """重读 common header，统一映射 closed/restart。"""

        common = unpack_common_header(
            self._require_view(),
            expected_kind=CHANNEL_KIND_RPC,
            expected_fingerprint=self.layout.fingerprint,
        )
        if common.owner_epoch != self.owner_epoch:
            raise ChannelRestartedError("RPC owner epoch 已变化")
        if common.flags & FILE_FLAG_CLOSED:
            raise ChannelClosedError("RPC owner 已关闭")

    def _identity_matches(
        self, header: tuple[object, ...], identity: RpcTransportIdentity
    ) -> bool:
        """比较 client descriptor fence。"""

        return (
            header[2] == identity.generation
            and header[3] == identity.owner_epoch
            and header[5] == identity.owner_token
        )

    def _read_descriptor(self, descriptor_index: int) -> tuple[object, ...]:
        """读取 descriptor header。"""

        return RPC_DESCRIPTOR_HEADER.unpack_from(
            self._require_view(), self._descriptor_offset(descriptor_index)
        )

    def _read_descriptor_extension(self, identity: RpcTransportIdentity) -> bytes:
        """在 identity 已校验后复制完整 descriptor 扩展区。"""

        start = self._descriptor_offset(identity.descriptor_index) + RPC_DESCRIPTOR_EXTENSION_OFFSET
        return bytes(
            self._require_view()[start : start + RPC_DESCRIPTOR_EXTENSION_SIZE]
        )

    def _write_descriptor_extension_locked(
        self,
        identity: RpcTransportIdentity,
        *,
        extension: bytes,
    ) -> None:
        """在 descriptor guard 内覆盖完整扩展区，避免旧 phase 残留。"""

        payload = bytes(extension)
        self._validate_extension_range(offset=0, size=len(payload))
        start = self._descriptor_offset(identity.descriptor_index) + RPC_DESCRIPTOR_EXTENSION_OFFSET
        view = self._require_view()
        view[start : start + RPC_DESCRIPTOR_EXTENSION_SIZE] = (
            payload.ljust(RPC_DESCRIPTOR_EXTENSION_SIZE, b"\0")
        )

    @staticmethod
    def _validate_extension_range(*, offset: int, size: int) -> None:
        """限制窄协议只能访问 descriptor 的保留扩展区。"""

        if offset < 0 or size < 0 or offset + size > RPC_DESCRIPTOR_EXTENSION_SIZE:
            raise ValueError("RPC descriptor extension 范围越界")

    def _descriptor_offset(self, descriptor_index: int) -> int:
        """返回 descriptor offset。"""

        return self.layout.descriptor_region_offset + descriptor_index * self.layout.descriptor_stride_bytes

    def _response_offset(self, descriptor_index: int) -> int:
        """返回 inline response offset。"""

        return (
            self._descriptor_offset(descriptor_index)
            + RPC_DESCRIPTOR_HEADER_SIZE
            + self.profile.inline_request_capacity_bytes
        )

    def _require_view(self) -> mmap.mmap:
        """返回活动 client view。"""

        if self._view is None:
            raise ChannelClosedError("RPC client 已关闭")
        return self._view

    def _close_handles(self) -> None:
        """幂等关闭 client mapping。"""

        view, file = self._view, self._file
        self._view = None
        self._file = None
        if view is not None:
            view.close()
        if file is not None:
            file.close()


def _error_from_code(error_code: int) -> LocalMessageChannelError:
    """把 wire error code 映射为稳定应用层错误。"""

    if error_code == RPC_ERROR_DEADLINE_EXCEEDED:
        return ChannelDeadlineExceededError("RPC request 超时")
    if error_code == RPC_ERROR_CANCELLED:
        return ChannelCancelledError("RPC request 已取消")
    if error_code == RPC_ERROR_INVALID_MESSAGE:
        return ChannelInvalidMessageError("RPC request 不合法")
    if error_code == RPC_ERROR_CAPACITY_EXHAUSTED:
        return ChannelCapacityExhaustedError("RPC 固定容量不足")
    if error_code == RPC_ERROR_SERVER_FAILURE:
        return LocalMessageChannelError("RPC server 执行失败")
    return ChannelCorruptMessageError(f"RPC 未知 error code: {error_code}")
