"""Workflow Trigger mailbox v1 的固定容量 mmap 状态机。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import mmap
import os
from pathlib import Path
import struct
from threading import Lock
from time import monotonic_ns, time_ns
from typing import BinaryIO, Iterator
from uuid import UUID, uuid4
import zlib

from backend.contracts.ipc import workflow_trigger_mailbox_v1 as contract
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.infrastructure.ipc.mmap_primitives import (
    MmapGuardBusyError,
    MmapPageChainError,
    acquire_mmap_guard,
    acquire_mmap_owner_lock,
    crc32_ieee,
    new_nonzero_u64_token,
    publish_u32,
    read_page_chain,
    release_mmap_owner_lock,
    select_page_indices,
    try_lock_byte_range_file,
    unlock_byte_range_file,
)
from backend.service.infrastructure.ipc.workflow_trigger_mailbox_path import (
    build_workflow_trigger_descriptor_guard_path,
    build_workflow_trigger_mailbox_path,
    build_workflow_trigger_owner_lock_path,
)


_U32 = struct.Struct("<I")
_I32 = struct.Struct("<i")
_U64 = struct.Struct("<Q")
_NO_PAGE_INDEX = -1
_COMPRESSION_THRESHOLD_BYTES = 256 * 1024
_COMPRESSION_MAX_RATIO = 0.875

DESCRIPTOR_STRIDE_BYTES = (
    contract.DESCRIPTOR_HEADER_SIZE
    + contract.INLINE_REQUEST_CAPACITY_BYTES
    + contract.INLINE_RESPONSE_CAPACITY_BYTES
)
PAGE_STRIDE_BYTES = contract.PAGE_HEADER_SIZE + contract.OVERFLOW_PAGE_CAPACITY_BYTES
DESCRIPTOR_REGION_OFFSET = contract.FILE_HEADER_SIZE
PAGE_REGION_OFFSET = (
    DESCRIPTOR_REGION_OFFSET + contract.DESCRIPTOR_COUNT * DESCRIPTOR_STRIDE_BYTES
)
MAILBOX_FILE_SIZE_BYTES = (
    PAGE_REGION_OFFSET + contract.OVERFLOW_PAGE_COUNT * PAGE_STRIDE_BYTES
)


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
    """描述 server 已校验但尚未分配 input lease 的 PREPARE。"""

    identity: WorkflowTriggerDescriptorIdentity
    payload: bytes
    route_generation: int
    accepted_timeout_ms: int


@dataclass(frozen=True)
class WorkflowTriggerMailboxAllocation:
    """描述 server 接受相对 timeout 后发布的 allocation 与权威 identity。"""

    identity: WorkflowTriggerDescriptorIdentity
    payload: bytes


@dataclass(frozen=True)
class WorkflowTriggerMailboxResponse:
    """描述 client 已校验并解码的 RESPONSE。"""

    identity: WorkflowTriggerDescriptorIdentity
    payload: bytes
    error_code: int
    response_output_lease_count: int
    handoff_state: int
    response_ack_deadline_ns: int

    def json_payload(self) -> dict[str, object]:
        """把 UTF-8 JSON response 解码为对象。"""

        value = json.loads(self.payload.decode("utf-8"))
        if not isinstance(value, dict):
            raise InvalidRequestError("Workflow Trigger response JSON 必须是对象")
        return value


class WorkflowTriggerMailboxServer:
    """持有 mailbox owner lock 的单 server 状态机。"""

    def __init__(
        self,
        *,
        buffers_root: str | Path,
        max_request_timeout_ms: int = 120_000,
        response_ack_timeout_ms: int = 30_000,
    ) -> None:
        """创建或接管固定 mailbox，并以新 server epoch 清空旧状态。"""

        if max_request_timeout_ms <= 0:
            raise ServiceConfigurationError(
                "Workflow Trigger 最大请求 timeout 必须大于 0"
            )
        if response_ack_timeout_ms <= 0:
            raise ServiceConfigurationError(
                "Workflow Trigger response ACK timeout 必须大于 0"
            )

        self.path = build_workflow_trigger_mailbox_path(buffers_root)
        self.max_request_timeout_ms = max_request_timeout_ms
        self.response_ack_timeout_ms = response_ack_timeout_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._owner_lock = acquire_mmap_owner_lock(
            build_workflow_trigger_owner_lock_path(self.path)
        )
        self._file: BinaryIO | None = None
        self._view: mmap.mmap | None = None
        self._descriptor_guard_paths = tuple(
            build_workflow_trigger_descriptor_guard_path(self.path, index)
            for index in range(contract.DESCRIPTOR_COUNT)
        )
        self.server_epoch = new_nonzero_u64_token()
        self._last_timeout_diagnostic: dict[str, int] | None = None
        self._prepare_poll_cursor = 0
        self._request_poll_cursor = 0
        # page pool 由单个 server 进程拥有，但多个 Runtime completion 线程会
        # 并发发布不同 descriptor 的响应。descriptor guard 不能保护共享 page
        # 选择，因此分配、回滚和释放必须经过同一把进程内 allocator lock。
        self._page_allocator_lock = Lock()
        try:
            self._initialize_descriptor_guard_files()
            self._file = self._open_fixed_file()
            self._view = mmap.mmap(
                self._file.fileno(),
                MAILBOX_FILE_SIZE_BYTES,
                access=mmap.ACCESS_WRITE,
            )
            self._initialize_mailbox()
        except Exception:
            self.close()
            raise

    def poll_prepare(self) -> WorkflowTriggerMailboxPrepare | None:
        """非阻塞扫描一条 PREPARE，并校验握手 payload。"""

        view = self._require_view()
        current_ns = monotonic_ns()
        for offset in range(contract.DESCRIPTOR_COUNT):
            descriptor_index = (
                self._prepare_poll_cursor + offset
            ) % contract.DESCRIPTOR_COUNT
            descriptor_offset = _descriptor_offset(descriptor_index)
            if _read_u32(
                view,
                descriptor_offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
            ) != contract.DESCRIPTOR_STATE_PREPARE:
                continue
            with self._try_descriptor_guard(descriptor_index) as acquired:
                if not acquired:
                    continue
                # state 是 descriptor 的发布字段；锁外读取只用于跳过明显
                # 不匹配的槽位，锁内必须再次校验以关闭 TOCTOU 窗口。
                if _read_u32(
                    view,
                    descriptor_offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
                ) != contract.DESCRIPTOR_STATE_PREPARE:
                    continue
                identity = self._read_identity(descriptor_index)
                if identity.server_epoch != self.server_epoch:
                    self._reset_descriptor_locked(identity)
                    continue
                requested_timeout_ms = _read_u32(
                    view,
                    descriptor_offset
                    + contract.DESCRIPTOR_HEADER_ACCEPTED_TIMEOUT_MS_OFFSET,
                )
                if identity.deadline_ns == 0:
                    accepted_timeout_ms = min(
                        max(requested_timeout_ms, 1),
                        self.max_request_timeout_ms,
                    )
                    _write_u32(
                        view,
                        descriptor_offset
                        + contract.DESCRIPTOR_HEADER_ACCEPTED_TIMEOUT_MS_OFFSET,
                        accepted_timeout_ms,
                    )
                    _write_u64(
                        view,
                        descriptor_offset
                        + contract.DESCRIPTOR_HEADER_DEADLINE_NS_OFFSET,
                        current_ns + accepted_timeout_ms * 1_000_000,
                    )
                    self._last_timeout_diagnostic = {
                        "requested_timeout_ms": requested_timeout_ms,
                        "accepted_timeout_ms": accepted_timeout_ms,
                        "accepted_at_ns": current_ns,
                    }
                identity = self._read_identity(descriptor_index)
                if current_ns >= identity.deadline_ns:
                    self._publish_deadline_exceeded_locked(identity)
                    continue
                try:
                    payload = self._read_request_payload_locked(identity)
                except InvalidRequestError as error:
                    self._publish_error_locked(
                        identity,
                        error_code=contract.ERROR_CODE_CHECKSUM_MISMATCH,
                        message=error.message,
                    )
                    continue
                self._prepare_poll_cursor = (
                    descriptor_index + 1
                ) % contract.DESCRIPTOR_COUNT
                return WorkflowTriggerMailboxPrepare(
                    identity=identity,
                    payload=payload,
                    route_generation=_read_u64(
                        view,
                        descriptor_offset
                        + contract.DESCRIPTOR_HEADER_ROUTE_GENERATION_OFFSET,
                    ),
                    accepted_timeout_ms=_read_u32(
                        view,
                        descriptor_offset
                        + contract.DESCRIPTOR_HEADER_ACCEPTED_TIMEOUT_MS_OFFSET,
                    ),
                )
        return None

    def publish_writing(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        allocation_payload: bytes,
    ) -> None:
        """发布 External LocalBuffer allocation 后允许 client 开始写图。"""

        if (
            not isinstance(allocation_payload, bytes)
            or len(allocation_payload) > contract.INLINE_RESPONSE_CAPACITY_BYTES
        ):
            raise InvalidRequestError(
                "Workflow Trigger allocation payload 必须是不超过 512 KiB 的 bytes"
            )
        with self._descriptor_guard(identity.descriptor_index, identity.deadline_ns):
            self._require_identity_locked(
                identity,
                expected_states={contract.DESCRIPTOR_STATE_PREPARE},
            )
            view = self._require_view()
            response_offset = _inline_response_offset(identity.descriptor_index)
            view[
                response_offset : response_offset + len(allocation_payload)
            ] = allocation_payload
            descriptor_offset = _descriptor_offset(identity.descriptor_index)
            _write_u32(
                view,
                descriptor_offset + contract.DESCRIPTOR_HEADER_RESPONSE_SIZE_OFFSET,
                len(allocation_payload),
            )
            _write_u32(
                view,
                descriptor_offset
                + contract.DESCRIPTOR_HEADER_RESPONSE_CHECKSUM_ALGORITHM_OFFSET,
                contract.CHECKSUM_ALGORITHM_CRC32_IEEE,
            )
            _write_u32(
                view,
                descriptor_offset
                + contract.DESCRIPTOR_HEADER_RESPONSE_CHECKSUM_OFFSET,
                crc32_ieee(allocation_payload),
            )
            _write_u64(
                view,
                descriptor_offset + contract.DESCRIPTOR_HEADER_UPDATED_AT_NS_OFFSET,
                time_ns(),
            )
            publish_u32(
                view,
                offset=descriptor_offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
                value=contract.DESCRIPTOR_STATE_WRITING,
            )

    def tighten_accepted_timeout(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        timeout_ms: int,
    ) -> WorkflowTriggerDescriptorIdentity:
        """按路由上限收紧已接受 timeout，不重新起算请求时间。"""

        if timeout_ms <= 0:
            raise InvalidRequestError("Workflow Trigger 路由 timeout 必须大于 0")
        with self._descriptor_guard(identity.descriptor_index, identity.deadline_ns):
            self._require_identity_locked(
                identity,
                expected_states={contract.DESCRIPTOR_STATE_PREPARE},
            )
            view = self._require_view()
            descriptor_offset = _descriptor_offset(identity.descriptor_index)
            current_timeout_ms = _read_u32(
                view,
                descriptor_offset
                + contract.DESCRIPTOR_HEADER_ACCEPTED_TIMEOUT_MS_OFFSET,
            )
            accepted_timeout_ms = min(current_timeout_ms, timeout_ms)
            accepted_at_ns = identity.deadline_ns - current_timeout_ms * 1_000_000
            _write_u32(
                view,
                descriptor_offset
                + contract.DESCRIPTOR_HEADER_ACCEPTED_TIMEOUT_MS_OFFSET,
                accepted_timeout_ms,
            )
            _write_u64(
                view,
                descriptor_offset + contract.DESCRIPTOR_HEADER_DEADLINE_NS_OFFSET,
                accepted_at_ns + accepted_timeout_ms * 1_000_000,
            )
            return self._read_identity(identity.descriptor_index)

    def poll_request(self) -> WorkflowTriggerMailboxRequest | None:
        """非阻塞扫描一条 REQUEST，校验后发布 PROCESSING。"""

        view = self._require_view()
        current_ns = monotonic_ns()
        for offset in range(contract.DESCRIPTOR_COUNT):
            descriptor_index = (
                self._request_poll_cursor + offset
            ) % contract.DESCRIPTOR_COUNT
            descriptor_offset = _descriptor_offset(descriptor_index)
            if _read_u32(
                view,
                descriptor_offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
            ) != contract.DESCRIPTOR_STATE_REQUEST:
                continue
            with self._try_descriptor_guard(descriptor_index) as acquired:
                if not acquired:
                    continue
                if _read_u32(view, descriptor_offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET) != contract.DESCRIPTOR_STATE_REQUEST:
                    continue
                identity = self._read_identity(descriptor_index)
                if identity.server_epoch != self.server_epoch:
                    self._reset_descriptor_locked(identity)
                    continue
                if current_ns >= identity.deadline_ns:
                    self._publish_deadline_exceeded_locked(identity)
                    continue
                try:
                    payload = self._read_request_payload_locked(identity)
                except InvalidRequestError as error:
                    self._publish_error_locked(
                        identity,
                        error_code=contract.ERROR_CODE_CHECKSUM_MISMATCH,
                        message=error.message,
                    )
                    continue
                _write_u64(
                    view,
                    descriptor_offset + contract.DESCRIPTOR_HEADER_UPDATED_AT_NS_OFFSET,
                    time_ns(),
                )
                publish_u32(
                    view,
                    offset=descriptor_offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
                    value=contract.DESCRIPTOR_STATE_PROCESSING,
                )
                self._request_poll_cursor = (
                    descriptor_index + 1
                ) % contract.DESCRIPTOR_COUNT
                return WorkflowTriggerMailboxRequest(
                    identity=identity,
                    payload=payload,
                    route_generation=_read_u64(
                        view,
                        descriptor_offset
                        + contract.DESCRIPTOR_HEADER_ROUTE_GENERATION_OFFSET,
                    ),
                    accepted_timeout_ms=_read_u32(
                        view,
                        descriptor_offset
                        + contract.DESCRIPTOR_HEADER_ACCEPTED_TIMEOUT_MS_OFFSET,
                    ),
                )
        return None

    def _read_request_payload_locked(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> bytes:
        """读取并验证 PREPARE/REQUEST 共用的 inline request 区。"""

        view = self._require_view()
        descriptor_offset = _descriptor_offset(identity.descriptor_index)
        request_size = _read_u32(
            view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_REQUEST_SIZE_OFFSET,
        )
        if request_size > contract.MAX_REQUEST_BYTES:
            raise InvalidRequestError("Workflow Trigger request 超过 512 KiB 上限")
        request_offset = _inline_request_offset(identity.descriptor_index)
        payload = bytes(view[request_offset : request_offset + request_size])
        checksum_algorithm = _read_u32(
            view,
            descriptor_offset
            + contract.DESCRIPTOR_HEADER_REQUEST_CHECKSUM_ALGORITHM_OFFSET,
        )
        checksum = _read_u32(
            view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_REQUEST_CHECKSUM_OFFSET,
        )
        if (
            checksum_algorithm != contract.CHECKSUM_ALGORITHM_CRC32_IEEE
            or crc32_ieee(payload) != checksum
        ):
            raise InvalidRequestError("Workflow Trigger request checksum 校验失败")
        return payload

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
        """一次序列化结果只写一次 inline/page-chain，最后发布 RESPONSE。"""

        if not isinstance(payload, bytes):
            raise InvalidRequestError("Workflow Trigger response 必须是 bytes")
        if len(payload) > contract.MAX_RESPONSE_BYTES:
            raise InvalidRequestError(
                "Workflow Trigger response 超过 32 MiB 上限",
                details={"response_size": len(payload)},
            )
        resolved_ack_deadline_ns = (
            response_ack_deadline_ns
            if response_ack_deadline_ns is not None
            else self.new_response_ack_deadline_ns()
        )
        if resolved_ack_deadline_ns <= monotonic_ns():
            raise InvalidRequestError(
                "Workflow Trigger response ACK deadline 必须位于未来"
            )
        with self._descriptor_guard(identity.descriptor_index, identity.deadline_ns):
            self._require_identity_locked(
                identity,
                expected_states={contract.DESCRIPTOR_STATE_PROCESSING},
            )
            descriptor_offset = _descriptor_offset(identity.descriptor_index)
            cancel_reason = _read_u32(
                self._require_view(),
                descriptor_offset
                + contract.DESCRIPTOR_HEADER_CANCEL_REASON_OFFSET,
            )
            if cancel_reason != contract.CANCEL_REASON_NONE:
                self._publish_cancelled_locked(identity)
                return contract.ERROR_CODE_CANCELLED
            if monotonic_ns() >= identity.deadline_ns:
                self._publish_deadline_exceeded_locked(identity)
                return contract.ERROR_CODE_DEADLINE_EXCEEDED
            return self._publish_response_locked(
                identity,
                payload=payload,
                error_code=error_code,
                response_output_lease_count=response_output_lease_count,
                handoff_state=handoff_state,
                response_ack_deadline_ns=resolved_ack_deadline_ns,
            )

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

        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return self.publish_response(
            identity=identity,
            payload=serialized,
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
        """在 PREPARE/WRITING/REQUEST/PROCESSING 任一失败点发布 inline 错误。"""

        states = expected_states or {
            contract.DESCRIPTOR_STATE_PREPARE,
            contract.DESCRIPTOR_STATE_WRITING,
            contract.DESCRIPTOR_STATE_REQUEST,
            contract.DESCRIPTOR_STATE_PROCESSING,
        }
        with self._descriptor_guard(identity.descriptor_index, identity.deadline_ns):
            self._require_identity_locked(identity, expected_states=states)
            descriptor_offset = _descriptor_offset(identity.descriptor_index)
            cancel_reason = _read_u32(
                self._require_view(),
                descriptor_offset + contract.DESCRIPTOR_HEADER_CANCEL_REASON_OFFSET,
            )
            if cancel_reason != contract.CANCEL_REASON_NONE:
                self._publish_cancelled_locked(identity)
                return contract.ERROR_CODE_CANCELLED
            if monotonic_ns() >= identity.deadline_ns:
                self._publish_deadline_exceeded_locked(identity)
                return contract.ERROR_CODE_DEADLINE_EXCEEDED
            return self._publish_error_locked(
                identity,
                error_code=error_code,
                message=message,
            )

    def new_response_ack_deadline_ns(self) -> int:
        """按 server 唯一配置生成独立于 request 的 ACK deadline。"""

        return monotonic_ns() + self.response_ack_timeout_ms * 1_000_000

    def read_cancel_reason(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> int:
        """锁外快速跳过无取消请求，命中后在 descriptor guard 内重验。"""

        descriptor_offset = _descriptor_offset(identity.descriptor_index)
        reason = _read_u32(
            self._require_view(),
            descriptor_offset + contract.DESCRIPTOR_HEADER_CANCEL_REASON_OFFSET,
        )
        if reason == contract.CANCEL_REASON_NONE:
            return reason
        with self._descriptor_guard(identity.descriptor_index, identity.deadline_ns):
            self._require_identity_locked(
                identity,
                expected_states={contract.DESCRIPTOR_STATE_PROCESSING},
            )
            return _read_u32(
                self._require_view(),
                descriptor_offset + contract.DESCRIPTOR_HEADER_CANCEL_REASON_OFFSET,
            )

    def sweep(
        self,
        *,
        now_ns: int | None = None,
        descriptor_indexes: tuple[int, ...] | None = None,
    ) -> dict[str, object]:
        """推进 ACK/CANCEL/deadline 回收，不等待任何 client。

        ``descriptor_indexes`` 为空时保持完整扫描语义，供维护、恢复和测试使用；
        热路径 supervisor 会传入活动 descriptor 加一个轮转槽位，避免 Windows
        上每 1 ms 对 128 个 guard 文件执行一次无效锁操作。
        """

        current_ns = now_ns if now_ns is not None else monotonic_ns()
        cancelled_count = 0
        deadline_exceeded_count = 0
        response_ack_timeout_count = 0
        released_count = 0
        cancelled_identities: list[WorkflowTriggerDescriptorIdentity] = []
        deadline_exceeded_identities: list[WorkflowTriggerDescriptorIdentity] = []
        response_ack_timeout_identities: list[WorkflowTriggerDescriptorIdentity] = []
        released_identities: list[WorkflowTriggerDescriptorIdentity] = []
        indexes = (
            range(contract.DESCRIPTOR_COUNT)
            if descriptor_indexes is None
            else dict.fromkeys(descriptor_indexes)
        )
        for descriptor_index in indexes:
            if not 0 <= descriptor_index < contract.DESCRIPTOR_COUNT:
                raise ValueError("descriptor_index 超出 Workflow Trigger mailbox 范围")
            descriptor_offset = _descriptor_offset(descriptor_index)
            view = self._require_view()
            state = _read_u32(
                view,
                descriptor_offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
            )
            if state == contract.DESCRIPTOR_STATE_FREE:
                continue
            # state 是 descriptor publication 字段。锁外读取仅决定“本轮无事
            # 可做”并允许下一轮重试，不执行任何状态变更，因此不会产生 TOCTOU
            # 所有权问题。正常 WRITING/REQUEST/PROCESSING/RESPONSE 等待不能每
            # 1 ms 打开 guard 文件，否则 Windows 会形成大量 NTFS metadata I/O。
            if state not in {
                contract.DESCRIPTOR_STATE_ACKED,
                contract.DESCRIPTOR_STATE_CANCELLED,
            }:
                cancel_reason = _read_u32(
                    view,
                    descriptor_offset + contract.DESCRIPTOR_HEADER_CANCEL_REASON_OFFSET,
                )
                deadline_offset = (
                    contract.DESCRIPTOR_HEADER_RESPONSE_ACK_DEADLINE_NS_OFFSET
                    if state == contract.DESCRIPTOR_STATE_RESPONSE
                    else contract.DESCRIPTOR_HEADER_DEADLINE_NS_OFFSET
                )
                deadline_ns = _read_u64(view, descriptor_offset + deadline_offset)
                if (
                    state == contract.DESCRIPTOR_STATE_PREPARE
                    and deadline_ns == 0
                    and cancel_reason == contract.CANCEL_REASON_NONE
                ) or (
                    cancel_reason == contract.CANCEL_REASON_NONE
                    and current_ns < deadline_ns
                ):
                    continue
            with self._try_descriptor_guard(descriptor_index) as acquired:
                if not acquired:
                    continue
                state = _read_u32(
                    view,
                    descriptor_offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
                )
                if state == contract.DESCRIPTOR_STATE_FREE:
                    continue
                identity = self._read_identity(descriptor_index)
                if state in {
                    contract.DESCRIPTOR_STATE_ACKED,
                    contract.DESCRIPTOR_STATE_CANCELLED,
                }:
                    self._reset_descriptor_locked(identity)
                    released_count += 1
                    released_identities.append(identity)
                    continue
                if (
                    state == contract.DESCRIPTOR_STATE_PREPARE
                    and identity.deadline_ns == 0
                ):
                    # client 只提交相对 timeout；poll_prepare 尚未接受前没有
                    # backend absolute deadline，terminal sweep 不得抢先取消。
                    continue
                cancel_reason = _read_u32(
                    view,
                    descriptor_offset + contract.DESCRIPTOR_HEADER_CANCEL_REASON_OFFSET,
                )
                if cancel_reason != contract.CANCEL_REASON_NONE:
                    self._publish_cancelled_locked(identity)
                    cancelled_count += 1
                    cancelled_identities.append(identity)
                    continue
                if state == contract.DESCRIPTOR_STATE_RESPONSE:
                    response_ack_deadline_ns = _read_u64(
                        view,
                        descriptor_offset
                        + contract.DESCRIPTOR_HEADER_RESPONSE_ACK_DEADLINE_NS_OFFSET,
                    )
                    if current_ns >= response_ack_deadline_ns:
                        self._publish_cancelled_locked(identity)
                        response_ack_timeout_count += 1
                        response_ack_timeout_identities.append(identity)
                    continue
                if current_ns >= identity.deadline_ns:
                    self._publish_deadline_exceeded_locked(identity)
                    deadline_exceeded_count += 1
                    deadline_exceeded_identities.append(identity)
        return {
            "cancelled_count": cancelled_count,
            "deadline_exceeded_count": deadline_exceeded_count,
            "response_ack_timeout_count": response_ack_timeout_count,
            "cancelled_identities": tuple(cancelled_identities),
            "deadline_exceeded_identities": tuple(deadline_exceeded_identities),
            "response_ack_timeout_identities": tuple(
                response_ack_timeout_identities
            ),
            "released_count": released_count,
            "released_identities": tuple(released_identities),
        }

    def build_status(self) -> dict[str, object]:
        """返回 descriptor/page 容量状态。"""

        view = self._require_view()
        descriptor_states = [0] * 8
        for index in range(contract.DESCRIPTOR_COUNT):
            state = _read_u32(
                view,
                _descriptor_offset(index) + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
            )
            if 0 <= state < len(descriptor_states):
                descriptor_states[state] += 1
        with self._page_allocator_lock:
            free_pages = sum(
                _read_u32(
                    view,
                    _page_offset(index) + contract.PAGE_HEADER_STATE_OFFSET,
                )
                == contract.PAGE_STATE_FREE
                for index in range(contract.OVERFLOW_PAGE_COUNT)
            )
        return {
            "contract_id": contract.CONTRACT_ID,
            "path": str(self.path),
            "server_epoch": self.server_epoch,
            "file_size_bytes": MAILBOX_FILE_SIZE_BYTES,
            "descriptor_state_counts": tuple(descriptor_states),
            "free_page_count": free_pages,
            "used_page_count": contract.OVERFLOW_PAGE_COUNT - free_pages,
            "last_timeout_diagnostic": (
                dict(self._last_timeout_diagnostic)
                if self._last_timeout_diagnostic is not None
                else None
            ),
        }

    def close(self) -> None:
        """关闭 mmap、文件和 owner lock。"""

        if self._view is not None:
            self._view.close()
            self._view = None
        if self._file is not None:
            self._file.close()
            self._file = None
        if self._owner_lock is not None:
            release_mmap_owner_lock(self._owner_lock)
            self._owner_lock = None

    def __enter__(self) -> WorkflowTriggerMailboxServer:
        """返回 server context。"""

        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """退出时释放 owner。"""

        self.close()

    def _open_fixed_file(self) -> BinaryIO:
        """打开并固定 mailbox 文件大小。"""

        try:
            file_handle = self.path.open("r+b")
        except FileNotFoundError:
            file_handle = self.path.open("w+b")
        if os.fstat(file_handle.fileno()).st_size != MAILBOX_FILE_SIZE_BYTES:
            file_handle.truncate(MAILBOX_FILE_SIZE_BYTES)
            file_handle.flush()
        return file_handle

    def _initialize_descriptor_guard_files(self) -> None:
        """在 mailbox owner 启动时一次性创建固定 descriptor guard。"""

        for path in self._descriptor_guard_paths:
            with path.open("a+b", buffering=0) as guard_file:
                if os.fstat(guard_file.fileno()).st_size < 1:
                    guard_file.truncate(1)

    def _initialize_mailbox(self) -> None:
        """在 owner lock 内以新 epoch 重建全部可变 header。"""

        view = self._require_view()
        view[: contract.FILE_HEADER_SIZE] = contract.FILE_HEADER_STRUCT.pack(
            contract.MAGIC,
            contract.VERSION,
            contract.FILE_HEADER_SIZE,
            contract.DESCRIPTOR_COUNT,
            contract.DESCRIPTOR_HEADER_SIZE,
            contract.INLINE_REQUEST_CAPACITY_BYTES,
            contract.INLINE_RESPONSE_CAPACITY_BYTES,
            DESCRIPTOR_STRIDE_BYTES,
            contract.OVERFLOW_PAGE_COUNT,
            contract.PAGE_HEADER_SIZE,
            contract.OVERFLOW_PAGE_CAPACITY_BYTES,
            PAGE_STRIDE_BYTES,
            contract.MAX_OVERFLOW_PAGES_PER_RESPONSE,
            contract.CHECKSUM_ALGORITHM_CRC32_IEEE,
            0,
            self.server_epoch,
            time_ns(),
            bytes(48),
        )
        for descriptor_index in range(contract.DESCRIPTOR_COUNT):
            offset = _descriptor_offset(descriptor_index)
            previous_generation = _read_u64(
                view,
                offset + contract.DESCRIPTOR_HEADER_GENERATION_OFFSET,
            )
            view[offset : offset + contract.DESCRIPTOR_HEADER_SIZE] = bytes(
                contract.DESCRIPTOR_HEADER_SIZE
            )
            _write_u32(
                view,
                offset + contract.DESCRIPTOR_HEADER_DESCRIPTOR_INDEX_OFFSET,
                descriptor_index,
            )
            _write_u64(
                view,
                offset + contract.DESCRIPTOR_HEADER_GENERATION_OFFSET,
                previous_generation,
            )
            _write_u64(
                view,
                offset + contract.DESCRIPTOR_HEADER_SERVER_EPOCH_OFFSET,
                self.server_epoch,
            )
            _write_i32(
                view,
                offset + contract.DESCRIPTOR_HEADER_FIRST_PAGE_INDEX_OFFSET,
                _NO_PAGE_INDEX,
            )
        for page_index in range(contract.OVERFLOW_PAGE_COUNT):
            offset = _page_offset(page_index)
            view[offset : offset + contract.PAGE_HEADER_SIZE] = bytes(
                contract.PAGE_HEADER_SIZE
            )
            _write_i32(
                view,
                offset + contract.PAGE_HEADER_NEXT_PAGE_INDEX_OFFSET,
                _NO_PAGE_INDEX,
            )
        view.flush()

    def _publish_response_locked(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
        *,
        payload: bytes,
        error_code: int,
        response_output_lease_count: int,
        handoff_state: int,
        response_ack_deadline_ns: int,
    ) -> int:
        """在 descriptor guard 内发布 inline 或 page-chain response。"""

        view = self._require_view()
        raw_size = len(payload)
        encoded = payload
        codec = contract.RESPONSE_CODEC_NONE
        if raw_size >= _COMPRESSION_THRESHOLD_BYTES:
            compressed = zlib.compress(payload, level=1)
            if len(compressed) <= int(raw_size * _COMPRESSION_MAX_RATIO):
                encoded = compressed
                codec = contract.RESPONSE_CODEC_ZLIB
        descriptor_offset = _descriptor_offset(identity.descriptor_index)
        page_indices: tuple[int, ...] = ()
        if len(encoded) <= contract.INLINE_RESPONSE_CAPACITY_BYTES:
            response_offset = _inline_response_offset(identity.descriptor_index)
            view[response_offset : response_offset + len(encoded)] = encoded
        else:
            page_count = (
                len(encoded) + contract.OVERFLOW_PAGE_CAPACITY_BYTES - 1
            ) // contract.OVERFLOW_PAGE_CAPACITY_BYTES
            if page_count > contract.MAX_OVERFLOW_PAGES_PER_RESPONSE:
                raise InvalidRequestError("Workflow Trigger response page 数超过上限")
            page_indices = self._reserve_pages(
                page_count=page_count,
                identity=identity,
            )
            if not page_indices:
                self._publish_error_locked(
                    identity,
                    error_code=contract.ERROR_CODE_TRIGGER_RESPONSE_CAPACITY_EXHAUSTED,
                    message="Workflow Trigger response page pool 已满载",
                )
                return contract.ERROR_CODE_TRIGGER_RESPONSE_CAPACITY_EXHAUSTED
            try:
                for ordinal, page_index in enumerate(page_indices):
                    chunk_start = ordinal * contract.OVERFLOW_PAGE_CAPACITY_BYTES
                    chunk = encoded[
                        chunk_start : chunk_start
                        + contract.OVERFLOW_PAGE_CAPACITY_BYTES
                    ]
                    self._write_reserved_page(
                        page_index=page_index,
                        chunk=chunk,
                        identity=identity,
                    )
            except Exception:
                self._release_reserved_pages(
                    identity=identity,
                    page_indices=page_indices,
                )
                raise
        _write_u32(
            view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_RESPONSE_SIZE_OFFSET,
            len(encoded),
        )
        _write_u32(
            view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_RESPONSE_RAW_SIZE_OFFSET,
            raw_size,
        )
        _write_u32(
            view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_RESPONSE_CODEC_OFFSET,
            codec,
        )
        _write_u32(
            view,
            descriptor_offset
            + contract.DESCRIPTOR_HEADER_RESPONSE_CHECKSUM_ALGORITHM_OFFSET,
            contract.CHECKSUM_ALGORITHM_CRC32_IEEE,
        )
        _write_u32(
            view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_RESPONSE_CHECKSUM_OFFSET,
            crc32_ieee(encoded),
        )
        _write_i32(
            view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_FIRST_PAGE_INDEX_OFFSET,
            page_indices[0] if page_indices else _NO_PAGE_INDEX,
        )
        _write_u32(
            view,
            descriptor_offset
            + contract.DESCRIPTOR_HEADER_RESPONSE_PAGE_COUNT_OFFSET,
            len(page_indices),
        )
        _write_u32(
            view,
            descriptor_offset
            + contract.DESCRIPTOR_HEADER_RESPONSE_OUTPUT_LEASE_COUNT_OFFSET,
            response_output_lease_count,
        )
        _write_u32(
            view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_HANDOFF_STATE_OFFSET,
            handoff_state,
        )
        _write_u32(
            view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_ERROR_CODE_OFFSET,
            error_code,
        )
        _write_u64(
            view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_UPDATED_AT_NS_OFFSET,
            time_ns(),
        )
        _write_u64(
            view,
            descriptor_offset
            + contract.DESCRIPTOR_HEADER_RESPONSE_ACK_DEADLINE_NS_OFFSET,
            response_ack_deadline_ns,
        )
        publish_u32(
            view,
            offset=descriptor_offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
            value=contract.DESCRIPTOR_STATE_RESPONSE,
        )
        return error_code

    def _publish_error_locked(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
        *,
        error_code: int,
        message: str,
    ) -> int:
        """发布不依赖 overflow page 的紧凑错误。"""

        payload = json.dumps(
            {"state": "failed", "error_code": error_code, "error_message": message},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return self._publish_response_locked(
            identity,
            payload=payload,
            error_code=error_code,
            response_output_lease_count=0,
            handoff_state=contract.HANDOFF_STATE_NONE,
            response_ack_deadline_ns=self.new_response_ack_deadline_ns(),
        )

    def _publish_deadline_exceeded_locked(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> int:
        """发布可读取的最小 deadline_exceeded inline RESPONSE。"""

        return self._publish_error_locked(
            identity,
            error_code=contract.ERROR_CODE_DEADLINE_EXCEEDED,
            message="Workflow Trigger request deadline 已到期",
        )

    def _write_reserved_page(
        self,
        *,
        page_index: int,
        chunk: bytes,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> None:
        """在 allocator lock 外写完已预留 page，最后发布 READY。"""

        view = self._require_view()
        page_offset = _page_offset(page_index)
        header = self._read_page_header(page_index)[1]
        if (
            header["state"] != contract.PAGE_STATE_RESERVED
            or header["descriptor_index"] != identity.descriptor_index
            or header["descriptor_generation"] != identity.generation
            or header["owner_token"] != identity.owner_token
            or header["server_epoch"] != identity.server_epoch
        ):
            raise InvalidRequestError(
                "Workflow Trigger response page reservation identity 不匹配",
                details={"page_index": page_index},
            )
        body_offset = page_offset + contract.PAGE_HEADER_SIZE
        view[body_offset : body_offset + len(chunk)] = chunk
        _write_u32(
            view,
            page_offset + contract.PAGE_HEADER_USED_SIZE_OFFSET,
            len(chunk),
        )
        _write_u32(
            view,
            page_offset + contract.PAGE_HEADER_CHECKSUM_ALGORITHM_OFFSET,
            contract.CHECKSUM_ALGORITHM_CRC32_IEEE,
        )
        _write_u32(
            view,
            page_offset + contract.PAGE_HEADER_CHECKSUM_OFFSET,
            crc32_ieee(chunk),
        )
        publish_u32(
            view,
            offset=page_offset + contract.PAGE_HEADER_STATE_OFFSET,
            value=contract.PAGE_STATE_READY,
        )

    def _reserve_pages(
        self,
        *,
        page_count: int,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> tuple[int, ...]:
        """原子选择 page 并写入不可混淆的 reservation identity。"""

        view = self._require_view()
        with self._page_allocator_lock:
            free_pages = tuple(
                index
                for index in range(contract.OVERFLOW_PAGE_COUNT)
                if _read_u32(
                    view,
                    _page_offset(index) + contract.PAGE_HEADER_STATE_OFFSET,
                )
                == contract.PAGE_STATE_FREE
            )
            selected = select_page_indices(
                free_page_indices=free_pages,
                page_count=page_count,
            )
            for ordinal, page_index in enumerate(selected):
                page_offset = _page_offset(page_index)
                view[page_offset : page_offset + contract.PAGE_HEADER_SIZE] = bytes(
                    contract.PAGE_HEADER_SIZE
                )
                _write_i32(
                    view,
                    page_offset + contract.PAGE_HEADER_NEXT_PAGE_INDEX_OFFSET,
                    selected[ordinal + 1]
                    if ordinal + 1 < len(selected)
                    else _NO_PAGE_INDEX,
                )
                _write_u32(
                    view,
                    page_offset + contract.PAGE_HEADER_DESCRIPTOR_INDEX_OFFSET,
                    identity.descriptor_index,
                )
                _write_u64(
                    view,
                    page_offset + contract.PAGE_HEADER_DESCRIPTOR_GENERATION_OFFSET,
                    identity.generation,
                )
                _write_u64(
                    view,
                    page_offset + contract.PAGE_HEADER_OWNER_TOKEN_OFFSET,
                    identity.owner_token,
                )
                _write_u64(
                    view,
                    page_offset + contract.PAGE_HEADER_SERVER_EPOCH_OFFSET,
                    identity.server_epoch,
                )
                _write_u32(
                    view,
                    page_offset + contract.PAGE_HEADER_ORDINAL_OFFSET,
                    ordinal,
                )
                publish_u32(
                    view,
                    offset=page_offset + contract.PAGE_HEADER_STATE_OFFSET,
                    value=contract.PAGE_STATE_RESERVED,
                )
            return selected

    def _release_pages_locked(self, identity: WorkflowTriggerDescriptorIdentity) -> None:
        """只释放完整 identity 匹配的 page chain。"""

        view = self._require_view()
        descriptor_offset = _descriptor_offset(identity.descriptor_index)
        page_count = _read_u32(
            view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_RESPONSE_PAGE_COUNT_OFFSET,
        )
        first_page_index = _read_i32(
            view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_FIRST_PAGE_INDEX_OFFSET,
        )
        if page_count == 0:
            return
        with self._page_allocator_lock:
            try:
                entries = read_page_chain(
                    first_page_index=first_page_index,
                    expected_page_count=page_count,
                    total_page_count=contract.OVERFLOW_PAGE_COUNT,
                    no_page_index=_NO_PAGE_INDEX,
                    read_header=self._read_page_header,
                )
            except MmapPageChainError:
                entries = tuple(
                    (index, self._read_page_header(index)[1])
                    for index in range(contract.OVERFLOW_PAGE_COUNT)
                )
            self._release_matching_pages_locked(
                identity=identity,
                entries=entries,
            )

    def _release_reserved_pages(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        page_indices: tuple[int, ...],
    ) -> None:
        """回滚尚未发布到 descriptor 的 RESERVED/READY pages。"""

        with self._page_allocator_lock:
            entries = tuple(
                (page_index, self._read_page_header(page_index)[1])
                for page_index in page_indices
            )
            self._release_matching_pages_locked(
                identity=identity,
                entries=entries,
            )

    def _release_matching_pages_locked(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        entries: tuple[tuple[int, dict[str, int]], ...],
    ) -> None:
        """在 allocator lock 内按完整 identity 归还 pages。"""

        view = self._require_view()
        for page_index, header in entries:
            if (
                header["descriptor_index"] != identity.descriptor_index
                or header["descriptor_generation"] != identity.generation
                or header["owner_token"] != identity.owner_token
                or header["server_epoch"] != identity.server_epoch
            ):
                continue
            page_offset = _page_offset(page_index)
            view[page_offset : page_offset + contract.PAGE_HEADER_SIZE] = bytes(
                contract.PAGE_HEADER_SIZE
            )
            _write_i32(
                view,
                page_offset + contract.PAGE_HEADER_NEXT_PAGE_INDEX_OFFSET,
                _NO_PAGE_INDEX,
            )

    def _read_page_header(self, page_index: int) -> tuple[int, dict[str, int]]:
        """返回 page chain helper 所需的 next index 和身份字段。"""

        view = self._require_view()
        offset = _page_offset(page_index)
        return (
            _read_i32(view, offset + contract.PAGE_HEADER_NEXT_PAGE_INDEX_OFFSET),
            {
                "state": _read_u32(
                    view, offset + contract.PAGE_HEADER_STATE_OFFSET
                ),
                "used_size": _read_u32(
                    view, offset + contract.PAGE_HEADER_USED_SIZE_OFFSET
                ),
                "checksum_algorithm": _read_u32(
                    view, offset + contract.PAGE_HEADER_CHECKSUM_ALGORITHM_OFFSET
                ),
                "checksum": _read_u32(
                    view, offset + contract.PAGE_HEADER_CHECKSUM_OFFSET
                ),
                "descriptor_index": _read_u32(
                    view, offset + contract.PAGE_HEADER_DESCRIPTOR_INDEX_OFFSET
                ),
                "descriptor_generation": _read_u64(
                    view,
                    offset + contract.PAGE_HEADER_DESCRIPTOR_GENERATION_OFFSET,
                ),
                "owner_token": _read_u64(
                    view, offset + contract.PAGE_HEADER_OWNER_TOKEN_OFFSET
                ),
                "server_epoch": _read_u64(
                    view, offset + contract.PAGE_HEADER_SERVER_EPOCH_OFFSET
                ),
                "ordinal": _read_u32(
                    view, offset + contract.PAGE_HEADER_ORDINAL_OFFSET
                ),
            },
        )

    def _publish_cancelled_locked(
        self, identity: WorkflowTriggerDescriptorIdentity
    ) -> None:
        """释放 response pages 后发布 CANCELLED。"""

        self._release_pages_locked(identity)
        descriptor_offset = _descriptor_offset(identity.descriptor_index)
        _write_u32(
            self._require_view(),
            descriptor_offset + contract.DESCRIPTOR_HEADER_ERROR_CODE_OFFSET,
            contract.ERROR_CODE_CANCELLED,
        )
        publish_u32(
            self._require_view(),
            offset=descriptor_offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
            value=contract.DESCRIPTOR_STATE_CANCELLED,
        )

    def _reset_descriptor_locked(
        self, identity: WorkflowTriggerDescriptorIdentity
    ) -> None:
        """按 identity 释放 page 并把 descriptor 归还 FREE。"""

        self._release_pages_locked(identity)
        view = self._require_view()
        offset = _descriptor_offset(identity.descriptor_index)
        generation = _read_u64(
            view,
            offset + contract.DESCRIPTOR_HEADER_GENERATION_OFFSET,
        )
        view[offset : offset + contract.DESCRIPTOR_HEADER_SIZE] = bytes(
            contract.DESCRIPTOR_HEADER_SIZE
        )
        _write_u32(
            view,
            offset + contract.DESCRIPTOR_HEADER_DESCRIPTOR_INDEX_OFFSET,
            identity.descriptor_index,
        )
        _write_u64(
            view,
            offset + contract.DESCRIPTOR_HEADER_GENERATION_OFFSET,
            generation,
        )
        _write_u64(
            view,
            offset + contract.DESCRIPTOR_HEADER_SERVER_EPOCH_OFFSET,
            self.server_epoch,
        )
        _write_i32(
            view,
            offset + contract.DESCRIPTOR_HEADER_FIRST_PAGE_INDEX_OFFSET,
            _NO_PAGE_INDEX,
        )
        publish_u32(
            view,
            offset=offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
            value=contract.DESCRIPTOR_STATE_FREE,
        )

    def _read_identity(self, descriptor_index: int) -> WorkflowTriggerDescriptorIdentity:
        """读取当前 descriptor identity。"""

        view = self._require_view()
        offset = _descriptor_offset(descriptor_index)
        request_id = UUID(
            bytes=bytes(
                view[
                    offset + contract.DESCRIPTOR_HEADER_REQUEST_ID_OFFSET :
                    offset + contract.DESCRIPTOR_HEADER_REQUEST_ID_OFFSET + 16
                ]
            )
        )
        return WorkflowTriggerDescriptorIdentity(
            descriptor_index=descriptor_index,
            generation=_read_u64(
                view, offset + contract.DESCRIPTOR_HEADER_GENERATION_OFFSET
            ),
            server_epoch=_read_u64(
                view, offset + contract.DESCRIPTOR_HEADER_SERVER_EPOCH_OFFSET
            ),
            request_id=request_id,
            owner_token=_read_u64(
                view, offset + contract.DESCRIPTOR_HEADER_OWNER_TOKEN_OFFSET
            ),
            deadline_ns=_read_u64(
                view, offset + contract.DESCRIPTOR_HEADER_DEADLINE_NS_OFFSET
            ),
        )

    def _require_identity_locked(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
        *,
        expected_states: set[int],
    ) -> None:
        """按完整 descriptor identity fence 校验状态。"""

        current = self._read_identity(identity.descriptor_index)
        state = _read_u32(
            self._require_view(),
            _descriptor_offset(identity.descriptor_index)
            + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
        )
        if current != identity or state not in expected_states:
            raise InvalidRequestError(
                "Workflow Trigger descriptor identity 或状态不匹配",
                details={"descriptor_index": identity.descriptor_index, "state": state},
            )

    @contextmanager
    def _descriptor_guard(self, descriptor_index: int, deadline_ns: int) -> Iterator[None]:
        """取得指定 descriptor guard。"""

        with acquire_mmap_guard(
            guard_path=build_workflow_trigger_descriptor_guard_path(
                self.path,
                descriptor_index,
            ),
            # request deadline 到期后仍需发布 deadline RESPONSE 或收敛终态。
            deadline_ns=max(deadline_ns, monotonic_ns() + 2_000_000),
            poll_interval_seconds=0.001,
        ):
            yield

    @contextmanager
    def _try_descriptor_guard(self, descriptor_index: int) -> Iterator[bool]:
        """单次非阻塞探测 descriptor guard。"""

        path = self._descriptor_guard_paths[descriptor_index]
        guard_file = path.open("r+b", buffering=0)
        acquired = False
        try:
            try:
                try_lock_byte_range_file(guard_file)
                acquired = True
            except (BlockingIOError, OSError):
                acquired = False
            yield acquired
        finally:
            if acquired:
                unlock_byte_range_file(guard_file)
            guard_file.close()

    def _require_view(self) -> mmap.mmap:
        """返回打开的 mmap。"""

        if self._view is None:
            raise ServiceConfigurationError("Workflow Trigger mailbox 已关闭")
        return self._view


class WorkflowTriggerMailboxClient:
    """供 Python harness 与后续 SDK 对齐的 mailbox client。"""

    def __init__(self, *, buffers_root: str | Path) -> None:
        """打开并校验已经由 server 初始化的 mailbox。"""

        self.path = build_workflow_trigger_mailbox_path(buffers_root)
        self._view: mmap.mmap | None = None
        self._descriptor_guard_paths = tuple(
            build_workflow_trigger_descriptor_guard_path(self.path, index)
            for index in range(contract.DESCRIPTOR_COUNT)
        )
        try:
            self._file = self.path.open("r+b")
        except OSError as error:
            raise ServiceConfigurationError(
                "Workflow Trigger mailbox 尚未启动",
                details={"path": str(self.path)},
            ) from error
        try:
            if os.fstat(self._file.fileno()).st_size != MAILBOX_FILE_SIZE_BYTES:
                raise ServiceConfigurationError("Workflow Trigger mailbox 文件大小不匹配")
            self._view = mmap.mmap(
                self._file.fileno(),
                MAILBOX_FILE_SIZE_BYTES,
                access=mmap.ACCESS_WRITE,
            )
            self._validate_file_header()
        except Exception:
            if self._view is not None:
                self._view.close()
                self._view = None
            self._file.close()
            raise

    @property
    def server_epoch(self) -> int:
        """返回连接时可见的 server epoch。"""

        return _read_u64(
            self._require_view(),
            contract.FILE_HEADER_SERVER_EPOCH_OFFSET,
        )

    def claim(
        self,
        *,
        timeout_ms: int,
        route_generation: int,
        prepare_payload: bytes = b"{}",
        request_id: UUID | None = None,
    ) -> WorkflowTriggerDescriptorIdentity:
        """认领一个 FREE descriptor 并发布 PREPARE。"""

        if timeout_ms <= 0 or timeout_ms > 0xFFFFFFFF:
            raise InvalidRequestError(
                "Workflow Trigger timeout_ms 必须位于 1..4294967295"
            )
        if (
            not isinstance(prepare_payload, bytes)
            or len(prepare_payload) > contract.MAX_REQUEST_BYTES
        ):
            raise InvalidRequestError(
                "Workflow Trigger PREPARE 必须是不超过 512 KiB 的 bytes"
            )
        owner_token = new_nonzero_u64_token()
        resolved_request_id = request_id or uuid4()
        for descriptor_index in range(contract.DESCRIPTOR_COUNT):
            try:
                with acquire_mmap_guard(
                    guard_path=build_workflow_trigger_descriptor_guard_path(
                        self.path,
                        descriptor_index,
                    ),
                    deadline_ns=monotonic_ns() + 2_000_000,
                    poll_interval_seconds=0.0002,
                ):
                    offset = _descriptor_offset(descriptor_index)
                    if _read_u32(
                        self._view,
                        offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
                    ) != contract.DESCRIPTOR_STATE_FREE:
                        continue
                    generation = (
                        _read_u64(
                            self._view,
                            offset + contract.DESCRIPTOR_HEADER_GENERATION_OFFSET,
                        )
                        + 1
                    ) & 0xFFFFFFFFFFFFFFFF
                    generation = generation or 1
                    self._view[
                        offset : offset + contract.DESCRIPTOR_HEADER_SIZE
                    ] = bytes(contract.DESCRIPTOR_HEADER_SIZE)
                    _write_u32(
                        self._view,
                        offset + contract.DESCRIPTOR_HEADER_DESCRIPTOR_INDEX_OFFSET,
                        descriptor_index,
                    )
                    _write_u64(
                        self._view,
                        offset + contract.DESCRIPTOR_HEADER_GENERATION_OFFSET,
                        generation,
                    )
                    _write_u64(
                        self._view,
                        offset + contract.DESCRIPTOR_HEADER_SERVER_EPOCH_OFFSET,
                        self.server_epoch,
                    )
                    self._view[
                        offset + contract.DESCRIPTOR_HEADER_REQUEST_ID_OFFSET :
                        offset + contract.DESCRIPTOR_HEADER_REQUEST_ID_OFFSET + 16
                    ] = resolved_request_id.bytes
                    _write_u64(
                        self._view,
                        offset + contract.DESCRIPTOR_HEADER_OWNER_TOKEN_OFFSET,
                        owner_token,
                    )
                    _write_u64(
                        self._view,
                        offset + contract.DESCRIPTOR_HEADER_DEADLINE_NS_OFFSET,
                        0,
                    )
                    _write_u32(
                        self._view,
                        offset
                        + contract.DESCRIPTOR_HEADER_ACCEPTED_TIMEOUT_MS_OFFSET,
                        timeout_ms,
                    )
                    _write_u64(
                        self._view,
                        offset + contract.DESCRIPTOR_HEADER_ROUTE_GENERATION_OFFSET,
                        route_generation,
                    )
                    request_offset = _inline_request_offset(descriptor_index)
                    self._view[
                        request_offset : request_offset + len(prepare_payload)
                    ] = prepare_payload
                    _write_u32(
                        self._view,
                        offset + contract.DESCRIPTOR_HEADER_REQUEST_SIZE_OFFSET,
                        len(prepare_payload),
                    )
                    _write_u32(
                        self._view,
                        offset
                        + contract.DESCRIPTOR_HEADER_REQUEST_CHECKSUM_ALGORITHM_OFFSET,
                        contract.CHECKSUM_ALGORITHM_CRC32_IEEE,
                    )
                    _write_u32(
                        self._view,
                        offset + contract.DESCRIPTOR_HEADER_REQUEST_CHECKSUM_OFFSET,
                        crc32_ieee(prepare_payload),
                    )
                    _write_i32(
                        self._view,
                        offset + contract.DESCRIPTOR_HEADER_FIRST_PAGE_INDEX_OFFSET,
                        _NO_PAGE_INDEX,
                    )
                    _write_u64(
                        self._view,
                        offset + contract.DESCRIPTOR_HEADER_UPDATED_AT_NS_OFFSET,
                        time_ns(),
                    )
                    publish_u32(
                        self._view,
                        offset=offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
                        value=contract.DESCRIPTOR_STATE_PREPARE,
                    )
                    return WorkflowTriggerDescriptorIdentity(
                        descriptor_index=descriptor_index,
                        generation=generation,
                        server_epoch=self.server_epoch,
                        request_id=resolved_request_id,
                        owner_token=owner_token,
                        deadline_ns=0,
                    )
            except MmapGuardBusyError:
                continue
        raise InvalidRequestError(
            "Workflow Trigger descriptor 已满载",
            details={"descriptor_count": contract.DESCRIPTOR_COUNT},
        )

    def read_writing_allocation(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> WorkflowTriggerMailboxAllocation | None:
        """读取 allocation 和 backend 已接受的权威 identity。"""

        with self._descriptor_guard(identity, local_deadline_ns=monotonic_ns() + 2_000_000):
            current_identity = self._require_claim_identity_locked(
                identity,
                expected_states={
                    contract.DESCRIPTOR_STATE_PREPARE,
                    contract.DESCRIPTOR_STATE_WRITING,
                    contract.DESCRIPTOR_STATE_CANCELLED,
                },
            )
            descriptor_offset = _descriptor_offset(identity.descriptor_index)
            state = _read_u32(
                self._require_view(),
                descriptor_offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
            )
            if state == contract.DESCRIPTOR_STATE_CANCELLED:
                raise InvalidRequestError("Workflow Trigger PREPARE 已取消")
            if state != contract.DESCRIPTOR_STATE_WRITING:
                return None
            size = _read_u32(
                self._require_view(),
                descriptor_offset + contract.DESCRIPTOR_HEADER_RESPONSE_SIZE_OFFSET,
            )
            offset = _inline_response_offset(identity.descriptor_index)
            payload = bytes(self._require_view()[offset : offset + size])
            checksum = _read_u32(
                self._require_view(),
                descriptor_offset
                + contract.DESCRIPTOR_HEADER_RESPONSE_CHECKSUM_OFFSET,
            )
            if crc32_ieee(payload) != checksum:
                raise InvalidRequestError(
                    "Workflow Trigger allocation checksum 校验失败"
                )
            return WorkflowTriggerMailboxAllocation(
                identity=current_identity,
                payload=payload,
            )

    def publish_request(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        payload: bytes,
    ) -> None:
        """在 descriptor guard 内写完 request 后最后发布 REQUEST。"""

        if not isinstance(payload, bytes) or len(payload) > contract.MAX_REQUEST_BYTES:
            raise InvalidRequestError("Workflow Trigger request 必须是不超过 512 KiB 的 bytes")
        with self._descriptor_guard(identity):
            self._require_identity_locked(
                identity,
                expected_states={contract.DESCRIPTOR_STATE_WRITING},
            )
            offset = _descriptor_offset(identity.descriptor_index)
            request_offset = _inline_request_offset(identity.descriptor_index)
            self._view[request_offset : request_offset + len(payload)] = payload
            _write_u32(
                self._view,
                offset + contract.DESCRIPTOR_HEADER_REQUEST_SIZE_OFFSET,
                len(payload),
            )
            _write_u32(
                self._view,
                offset
                + contract.DESCRIPTOR_HEADER_REQUEST_CHECKSUM_ALGORITHM_OFFSET,
                contract.CHECKSUM_ALGORITHM_CRC32_IEEE,
            )
            _write_u32(
                self._view,
                offset + contract.DESCRIPTOR_HEADER_REQUEST_CHECKSUM_OFFSET,
                crc32_ieee(payload),
            )
            _write_u64(
                self._view,
                offset + contract.DESCRIPTOR_HEADER_UPDATED_AT_NS_OFFSET,
                time_ns(),
            )
            publish_u32(
                self._view,
                offset=offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
                value=contract.DESCRIPTOR_STATE_REQUEST,
            )

    def read_response(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> WorkflowTriggerMailboxResponse | None:
        """非阻塞读取并校验 RESPONSE；尚未完成时返回 None。"""

        with self._descriptor_guard(identity):
            current_identity = self._require_identity_locked(
                identity,
                expected_states={
                    contract.DESCRIPTOR_STATE_REQUEST,
                    contract.DESCRIPTOR_STATE_PROCESSING,
                    contract.DESCRIPTOR_STATE_RESPONSE,
                    contract.DESCRIPTOR_STATE_CANCELLED,
                },
            )
            descriptor_offset = _descriptor_offset(identity.descriptor_index)
            state = _read_u32(
                self._view,
                descriptor_offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
            )
            if state == contract.DESCRIPTOR_STATE_CANCELLED:
                raise InvalidRequestError("Workflow Trigger 请求已取消")
            if state != contract.DESCRIPTOR_STATE_RESPONSE:
                return None
            encoded = self._read_encoded_response_locked(identity)
            checksum = _read_u32(
                self._view,
                descriptor_offset + contract.DESCRIPTOR_HEADER_RESPONSE_CHECKSUM_OFFSET,
            )
            if crc32_ieee(encoded) != checksum:
                raise InvalidRequestError("Workflow Trigger response checksum 校验失败")
            codec = _read_u32(
                self._view,
                descriptor_offset + contract.DESCRIPTOR_HEADER_RESPONSE_CODEC_OFFSET,
            )
            if codec == contract.RESPONSE_CODEC_NONE:
                payload = encoded
            elif codec == contract.RESPONSE_CODEC_ZLIB:
                payload = zlib.decompress(encoded)
            else:
                raise InvalidRequestError("Workflow Trigger response codec 不受支持")
            raw_size = _read_u32(
                self._view,
                descriptor_offset + contract.DESCRIPTOR_HEADER_RESPONSE_RAW_SIZE_OFFSET,
            )
            if len(payload) != raw_size:
                raise InvalidRequestError("Workflow Trigger response 解压长度不匹配")
            return WorkflowTriggerMailboxResponse(
                identity=current_identity,
                payload=payload,
                error_code=_read_u32(
                    self._view,
                    descriptor_offset + contract.DESCRIPTOR_HEADER_ERROR_CODE_OFFSET,
                ),
                response_output_lease_count=_read_u32(
                    self._view,
                    descriptor_offset
                    + contract.DESCRIPTOR_HEADER_RESPONSE_OUTPUT_LEASE_COUNT_OFFSET,
                ),
                handoff_state=_read_u32(
                    self._view,
                    descriptor_offset + contract.DESCRIPTOR_HEADER_HANDOFF_STATE_OFFSET,
                ),
                response_ack_deadline_ns=_read_u64(
                    self._view,
                    descriptor_offset
                    + contract.DESCRIPTOR_HEADER_RESPONSE_ACK_DEADLINE_NS_OFFSET,
                ),
            )

    def acknowledge(self, *, identity: WorkflowTriggerDescriptorIdentity) -> None:
        """在完整读取校验后发布 ACKED。"""

        with self._descriptor_guard(identity):
            self._require_identity_locked(
                identity,
                expected_states={contract.DESCRIPTOR_STATE_RESPONSE},
            )
            publish_u32(
                self._view,
                offset=_descriptor_offset(identity.descriptor_index)
                + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
                value=contract.DESCRIPTOR_STATE_ACKED,
            )

    def cancel(
        self,
        *,
        identity: WorkflowTriggerDescriptorIdentity,
        reason: int = contract.CANCEL_REASON_EXPLICIT,
    ) -> None:
        """请求取消；PROCESSING 只置位，其他未完成状态直接发布 CANCELLED。"""

        if reason not in {
            contract.CANCEL_REASON_REQUEST_TIMEOUT,
            contract.CANCEL_REASON_EXPLICIT,
            contract.CANCEL_REASON_CLIENT_SHUTDOWN,
        }:
            raise InvalidRequestError("Workflow Trigger cancel reason 不合法")

        with self._descriptor_guard(identity):
            self._require_identity_locked(
                identity,
                expected_states={
                    contract.DESCRIPTOR_STATE_PREPARE,
                    contract.DESCRIPTOR_STATE_WRITING,
                    contract.DESCRIPTOR_STATE_REQUEST,
                    contract.DESCRIPTOR_STATE_PROCESSING,
                    contract.DESCRIPTOR_STATE_RESPONSE,
                },
            )
            offset = _descriptor_offset(identity.descriptor_index)
            state = _read_u32(
                self._view,
                offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
            )
            current_reason = _read_u32(
                self._view,
                offset + contract.DESCRIPTOR_HEADER_CANCEL_REASON_OFFSET,
            )
            if current_reason == contract.CANCEL_REASON_NONE:
                _write_u32(
                    self._view,
                    offset + contract.DESCRIPTOR_HEADER_CANCEL_REASON_OFFSET,
                    reason,
                )
            if state != contract.DESCRIPTOR_STATE_PROCESSING:
                publish_u32(
                    self._view,
                    offset=offset + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
                    value=contract.DESCRIPTOR_STATE_CANCELLED,
                )

    def close(self) -> None:
        """关闭 client view。"""

        if self._view is not None:
            self._view.close()
            self._view = None
        if not self._file.closed:
            self._file.close()

    def __enter__(self) -> WorkflowTriggerMailboxClient:
        """返回 client context。"""

        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """退出时关闭 view。"""

        self.close()

    def _read_encoded_response_locked(
        self, identity: WorkflowTriggerDescriptorIdentity
    ) -> bytes:
        """读取 inline 或完整 page-chain encoded response。"""

        descriptor_offset = _descriptor_offset(identity.descriptor_index)
        response_size = _read_u32(
            self._view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_RESPONSE_SIZE_OFFSET,
        )
        page_count = _read_u32(
            self._view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_RESPONSE_PAGE_COUNT_OFFSET,
        )
        if page_count == 0:
            offset = _inline_response_offset(identity.descriptor_index)
            return bytes(self._view[offset : offset + response_size])
        first_page_index = _read_i32(
            self._view,
            descriptor_offset + contract.DESCRIPTOR_HEADER_FIRST_PAGE_INDEX_OFFSET,
        )
        try:
            entries = read_page_chain(
                first_page_index=first_page_index,
                expected_page_count=page_count,
                total_page_count=contract.OVERFLOW_PAGE_COUNT,
                no_page_index=_NO_PAGE_INDEX,
                read_header=self._read_page_header,
            )
        except MmapPageChainError as error:
            raise InvalidRequestError(
                "Workflow Trigger response page chain 不合法",
                details={"reason": error.reason, "page_index": error.page_index},
            ) from error
        chunks: list[bytes] = []
        for expected_ordinal, (page_index, header) in enumerate(entries):
            if (
                header["state"] != contract.PAGE_STATE_READY
                or header["descriptor_index"] != identity.descriptor_index
                or header["descriptor_generation"] != identity.generation
                or header["owner_token"] != identity.owner_token
                or header["server_epoch"] != identity.server_epoch
                or header["ordinal"] != expected_ordinal
                or header["checksum_algorithm"]
                != contract.CHECKSUM_ALGORITHM_CRC32_IEEE
            ):
                raise InvalidRequestError("Workflow Trigger response page identity 不匹配")
            body_offset = _page_offset(page_index) + contract.PAGE_HEADER_SIZE
            chunk = bytes(
                self._view[body_offset : body_offset + header["used_size"]]
            )
            if crc32_ieee(chunk) != header["checksum"]:
                raise InvalidRequestError("Workflow Trigger response page checksum 失败")
            chunks.append(chunk)
        encoded = b"".join(chunks)
        if len(encoded) != response_size:
            raise InvalidRequestError("Workflow Trigger response page 总长度不匹配")
        return encoded

    def _read_page_header(self, page_index: int) -> tuple[int, dict[str, int]]:
        """读取 client 侧 page header。"""

        offset = _page_offset(page_index)
        return (
            _read_i32(
                self._view,
                offset + contract.PAGE_HEADER_NEXT_PAGE_INDEX_OFFSET,
            ),
            {
                "state": _read_u32(
                    self._view, offset + contract.PAGE_HEADER_STATE_OFFSET
                ),
                "used_size": _read_u32(
                    self._view, offset + contract.PAGE_HEADER_USED_SIZE_OFFSET
                ),
                "checksum_algorithm": _read_u32(
                    self._view,
                    offset + contract.PAGE_HEADER_CHECKSUM_ALGORITHM_OFFSET,
                ),
                "checksum": _read_u32(
                    self._view, offset + contract.PAGE_HEADER_CHECKSUM_OFFSET
                ),
                "descriptor_index": _read_u32(
                    self._view,
                    offset + contract.PAGE_HEADER_DESCRIPTOR_INDEX_OFFSET,
                ),
                "descriptor_generation": _read_u64(
                    self._view,
                    offset + contract.PAGE_HEADER_DESCRIPTOR_GENERATION_OFFSET,
                ),
                "owner_token": _read_u64(
                    self._view, offset + contract.PAGE_HEADER_OWNER_TOKEN_OFFSET
                ),
                "server_epoch": _read_u64(
                    self._view, offset + contract.PAGE_HEADER_SERVER_EPOCH_OFFSET
                ),
                "ordinal": _read_u32(
                    self._view, offset + contract.PAGE_HEADER_ORDINAL_OFFSET
                ),
            },
        )

    def _require_identity_locked(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
        *,
        expected_states: set[int],
    ) -> WorkflowTriggerDescriptorIdentity:
        """校验稳定 identity；claim 阶段允许尚未收到 backend deadline。"""

        current = self._read_identity(identity.descriptor_index)
        state = _read_u32(
            self._view,
            _descriptor_offset(identity.descriptor_index)
            + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
        )
        identity_matches = current == identity
        if identity.deadline_ns == 0:
            identity_matches = (
                current.descriptor_index == identity.descriptor_index
                and current.generation == identity.generation
                and current.server_epoch == identity.server_epoch
                and current.request_id == identity.request_id
                and current.owner_token == identity.owner_token
            )
        if not identity_matches or state not in expected_states:
            raise InvalidRequestError("Workflow Trigger descriptor identity 或状态不匹配")
        return current

    def _read_identity(self, descriptor_index: int) -> WorkflowTriggerDescriptorIdentity:
        """读取 client 当前 descriptor identity。"""

        offset = _descriptor_offset(descriptor_index)
        request_bytes = bytes(
            self._view[
                offset + contract.DESCRIPTOR_HEADER_REQUEST_ID_OFFSET :
                offset + contract.DESCRIPTOR_HEADER_REQUEST_ID_OFFSET + 16
            ]
        )
        return WorkflowTriggerDescriptorIdentity(
            descriptor_index=descriptor_index,
            generation=_read_u64(
                self._view, offset + contract.DESCRIPTOR_HEADER_GENERATION_OFFSET
            ),
            server_epoch=_read_u64(
                self._view, offset + contract.DESCRIPTOR_HEADER_SERVER_EPOCH_OFFSET
            ),
            request_id=UUID(bytes=request_bytes),
            owner_token=_read_u64(
                self._view, offset + contract.DESCRIPTOR_HEADER_OWNER_TOKEN_OFFSET
            ),
            deadline_ns=_read_u64(
                self._view, offset + contract.DESCRIPTOR_HEADER_DEADLINE_NS_OFFSET
            ),
        )

    @contextmanager
    def _descriptor_guard(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
        *,
        local_deadline_ns: int | None = None,
    ) -> Iterator[None]:
        """使用 client 自身 monotonic deadline 取得 descriptor guard。"""

        with acquire_mmap_guard(
            guard_path=self._descriptor_guard_paths[identity.descriptor_index],
            deadline_ns=(
                local_deadline_ns
                if local_deadline_ns is not None
                else monotonic_ns() + 2_000_000
            ),
            poll_interval_seconds=0.001,
        ):
            yield

    def _require_claim_identity_locked(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
        *,
        expected_states: set[int],
    ) -> WorkflowTriggerDescriptorIdentity:
        """允许 claim identity 的 deadline 为 0，并返回 backend 权威 identity。"""

        current = self._read_identity(identity.descriptor_index)
        state = _read_u32(
            self._view,
            _descriptor_offset(identity.descriptor_index)
            + contract.DESCRIPTOR_HEADER_STATE_OFFSET,
        )
        stable_matches = (
            current.descriptor_index == identity.descriptor_index
            and current.generation == identity.generation
            and current.server_epoch == identity.server_epoch
            and current.request_id == identity.request_id
            and current.owner_token == identity.owner_token
        )
        if not stable_matches or state not in expected_states:
            raise InvalidRequestError(
                "Workflow Trigger descriptor identity 或状态不匹配"
            )
        return current

    def _require_view(self) -> mmap.mmap:
        """返回打开的 client mmap。"""

        if self._view is None:
            raise ServiceConfigurationError("Workflow Trigger mailbox client 已关闭")
        return self._view

    def _validate_file_header(self) -> None:
        """拒绝不同 layout、epoch 或容量的 mailbox。"""

        values = contract.FILE_HEADER_STRUCT.unpack_from(self._view, 0)
        if (
            values[0] != contract.MAGIC
            or values[1] != contract.VERSION
            or values[2] != contract.FILE_HEADER_SIZE
            or values[3] != contract.DESCRIPTOR_COUNT
            or values[7] != DESCRIPTOR_STRIDE_BYTES
            or values[8] != contract.OVERFLOW_PAGE_COUNT
            or values[11] != PAGE_STRIDE_BYTES
            or values[13] != contract.CHECKSUM_ALGORITHM_CRC32_IEEE
        ):
            raise ServiceConfigurationError("Workflow Trigger mailbox header 不匹配")


def _descriptor_offset(descriptor_index: int) -> int:
    """返回 descriptor header 起始偏移。"""

    return DESCRIPTOR_REGION_OFFSET + descriptor_index * DESCRIPTOR_STRIDE_BYTES


def _inline_request_offset(descriptor_index: int) -> int:
    """返回 inline request 起始偏移。"""

    return _descriptor_offset(descriptor_index) + contract.DESCRIPTOR_HEADER_SIZE


def _inline_response_offset(descriptor_index: int) -> int:
    """返回 inline response 起始偏移。"""

    return _inline_request_offset(descriptor_index) + contract.INLINE_REQUEST_CAPACITY_BYTES


def _page_offset(page_index: int) -> int:
    """返回 overflow page header 起始偏移。"""

    return PAGE_REGION_OFFSET + page_index * PAGE_STRIDE_BYTES


def _read_u32(view: mmap.mmap, offset: int) -> int:
    """读取 little-endian u32。"""

    return _U32.unpack_from(view, offset)[0]


def _write_u32(view: mmap.mmap, offset: int, value: int) -> None:
    """写入 little-endian u32。"""

    _U32.pack_into(view, offset, value)


def _read_i32(view: mmap.mmap, offset: int) -> int:
    """读取 little-endian i32。"""

    return _I32.unpack_from(view, offset)[0]


def _write_i32(view: mmap.mmap, offset: int, value: int) -> None:
    """写入 little-endian i32。"""

    _I32.pack_into(view, offset, value)


def _read_u64(view: mmap.mmap, offset: int) -> int:
    """读取 little-endian u64。"""

    return _U64.unpack_from(view, offset)[0]


def _write_u64(view: mmap.mmap, offset: int, value: int) -> None:
    """写入 little-endian u64。"""

    _U64.pack_into(view, offset, value)
