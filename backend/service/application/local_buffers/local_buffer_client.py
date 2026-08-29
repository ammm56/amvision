"""LocalBufferBroker 单 arena 客户端协议与事件通道。"""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
import mmap
from pathlib import Path
from queue import Empty
from threading import Lock, RLock
from time import monotonic_ns
from typing import Any, Iterator, Protocol
from uuid import uuid4

from backend.contracts.buffers import BufferLease, BufferRef, FrameRef
from backend.contracts.buffers.lease_ownership import (
    ExternalBufferAllocation,
    LeaseOwnershipReceipt,
)
from backend.service.application.errors import (
    InvalidRequestError,
    LocalBufferCapacityError,
    OperationTimeoutError,
    ServiceConfigurationError,
)
from backend.service.application.runtime.support.safe_counter import (
    SafeCounterState,
    increment_safe_counter,
    snapshot_safe_counter,
)
from backend.service.infrastructure.ipc.mmap_primitives import (
    acquire_mmap_guard,
    acquire_mmap_reader_guard,
)
from backend.service.infrastructure.local_buffers import (
    ExternalBufferCommitTransferResult,
    LocalBufferWriteResult,
)


LocalBufferContent = bytes | bytearray | memoryview


class LocalBufferReader(Protocol):
    """定义 Workflow 节点读取和释放 LocalBuffer 引用的最小接口。"""

    def read_buffer_ref(self, buffer_ref: BufferRef) -> bytes | memoryview: ...

    def read_frame_ref(self, frame_ref: FrameRef) -> bytes | memoryview: ...

    def release(self, lease_id: str) -> None: ...

    def release_owner(
        self,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
        owner_id_prefix: str | None = None,
    ) -> int: ...

    def expire_leases(self) -> int: ...


@dataclass(frozen=True)
class LocalBufferBrokerEventChannel:
    """描述访问 Broker 状态机所需的进程间事件通道。"""

    request_queue: Any
    response_queue: Any
    request_timeout_seconds: float = 5.0
    channel_id: str | None = None
    direct_access_settings: dict[str, object] | None = None


class LocalBufferBrokerClient:
    """通过控制通道访问 Broker，图片 bytes 直接读写固定 arena。"""

    def __init__(self, channel: LocalBufferBrokerEventChannel) -> None:
        """初始化控制计数、延迟 direct mmap 和 writer locator cache。"""

        self.channel = channel
        self._mmap_cache = _MmapFileCache()
        self._writer_locations: dict[str, dict[str, object]] = {}
        self._direct_access_settings = channel.direct_access_settings
        self._direct_access = None
        self._direct_reader = None
        self._direct_writer = None
        self._direct_access_lock = Lock()
        self._closed = False
        self._request_count = SafeCounterState()
        self._error_count = SafeCounterState()
        self._last_error: dict[str, object] | None = None
        self._request_response_lock = Lock()

    def get_status(self) -> dict[str, object]:
        """读取 Broker arena、容量守恒和健康摘要。"""

        return self._send_request(action="status", payload={})

    def write_bytes(
        self,
        *,
        content: LocalBufferContent,
        owner_kind: str,
        owner_id: str,
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> LocalBufferWriteResult:
        """按精确 content length 动态分配、直接写 arena 并发布引用。"""

        normalized = _normalize_write_content(content)
        lease = self.allocate_buffer(
            content_length=len(normalized),
            owner_kind=owner_kind,
            owner_id=owner_id,
            ttl_seconds=ttl_seconds,
            trace_id=trace_id,
        )
        try:
            self.write_lease_bytes(lease=lease, content=normalized)
            return self.commit_buffer(
                lease=lease,
                media_type=media_type,
                shape=shape,
                dtype=dtype,
                layout=layout,
                pixel_format=pixel_format,
            )
        except Exception:
            try:
                self.release(lease.lease_id)
            except Exception:
                pass
            raise

    def write_many(
        self,
        *,
        items: tuple[dict[str, object], ...],
        owner_kind: str,
        owner_id: str,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> tuple[LocalBufferWriteResult, ...]:
        """用两次控制往返分配并发布一批有序 bytes，内容仍直接写 mmap。"""

        if not items:
            raise InvalidRequestError("批量写入至少需要 1 个 item")
        if len(items) > 256:
            raise InvalidRequestError("批量写入 item 数量不能大于 256")
        normalized_items: list[dict[str, object]] = []
        for item_index, item in enumerate(items):
            content = _normalize_write_content(item.get("content"))
            media_type = item.get("media_type")
            if not isinstance(media_type, str) or not media_type.strip():
                raise InvalidRequestError(
                    "批量写入 item 缺少 media_type",
                    details={"item_index": item_index},
                )
            shape_value = item.get("shape", ())
            if not isinstance(shape_value, tuple | list):
                raise InvalidRequestError(
                    "批量写入 item shape 必须是数组",
                    details={"item_index": item_index},
                )
            normalized_items.append(
                {
                    "content": content,
                    "media_type": media_type.strip(),
                    "shape": tuple(int(value) for value in shape_value),
                    "dtype": item.get("dtype"),
                    "layout": item.get("layout"),
                    "pixel_format": item.get("pixel_format"),
                }
            )

        allocation_payload = self._send_request(
            action="allocate-buffers",
            payload={
                "items": [
                    {"content_length": len(item["content"])}
                    for item in normalized_items
                ],
                "owner_kind": owner_kind,
                "owner_id": owner_id,
                "ttl_seconds": ttl_seconds,
                "trace_id": trace_id,
            },
        )
        raw_allocations = allocation_payload.get("allocations")
        if not isinstance(raw_allocations, list) or len(raw_allocations) != len(
            normalized_items
        ):
            raise ServiceConfigurationError("Broker 批量分配响应数量不一致")
        leases: list[BufferLease] = []
        for raw_allocation in raw_allocations:
            if not isinstance(raw_allocation, dict):
                raise ServiceConfigurationError("Broker 批量分配响应格式无效")
            lease = BufferLease.model_validate(_require_dict(raw_allocation, "lease"))
            leases.append(lease)
            self._writer_locations[lease.lease_id] = _require_dict(
                raw_allocation,
                "writer",
            )

        try:
            for lease, item in zip(leases, normalized_items, strict=True):
                self.write_lease_bytes(lease=lease, content=item["content"])
            commit_payload = self._send_request(
                action="commit-buffers",
                payload={
                    "items": [
                        {
                            "lease": lease.model_dump(mode="json"),
                            "media_type": item["media_type"],
                            "shape": item["shape"],
                            "dtype": item["dtype"],
                            "layout": item["layout"],
                            "pixel_format": item["pixel_format"],
                        }
                        for lease, item in zip(
                            leases,
                            normalized_items,
                            strict=True,
                        )
                    ]
                },
            )
            raw_results = commit_payload.get("results")
            if not isinstance(raw_results, list) or len(raw_results) != len(leases):
                raise ServiceConfigurationError("Broker 批量发布响应数量不一致")
            results = tuple(
                LocalBufferWriteResult(
                    lease=BufferLease.model_validate(_require_dict(item, "lease")),
                    buffer_ref=BufferRef.model_validate(
                        _require_dict(item, "buffer_ref")
                    ),
                )
                for item in raw_results
                if isinstance(item, dict)
            )
            if len(results) != len(leases):
                raise ServiceConfigurationError("Broker 批量发布响应格式无效")
            return results
        except Exception:
            try:
                self.release_many(tuple(lease.lease_id for lease in leases))
            except Exception:
                pass
            raise
        finally:
            for lease in leases:
                self._writer_locations.pop(lease.lease_id, None)

    def allocate_buffer(
        self,
        *,
        content_length: int,
        owner_kind: str,
        owner_id: str,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> BufferLease:
        """申请普通 WRITING extent 并缓存内部 writer locator。"""

        payload = self._send_request(
            action="allocate-buffer",
            payload={
                "content_length": content_length,
                "owner_kind": owner_kind,
                "owner_id": owner_id,
                "ttl_seconds": ttl_seconds,
                "trace_id": trace_id,
            },
        )
        lease = BufferLease.model_validate(_require_dict(payload, "lease"))
        self._writer_locations[lease.lease_id] = _require_dict(payload, "writer")
        return lease

    def allocate_external_buffer(
        self,
        *,
        content_length: int,
        owner_kind: str,
        owner_id: str,
        deadline_ns: int,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> ExternalBufferAllocation:
        """为可信本机 external writer 申请精确 extent。"""

        payload = self._send_request(
            action="allocate-external-buffer",
            payload={
                "content_length": content_length,
                "owner_kind": owner_kind,
                "owner_id": owner_id,
                "deadline_ns": deadline_ns,
                "ttl_seconds": ttl_seconds,
                "trace_id": trace_id,
            },
        )
        allocation = ExternalBufferAllocation.model_validate(
            _require_dict(payload, "allocation")
        )
        self._writer_locations[allocation.lease.lease_id] = _require_dict(
            payload,
            "writer",
        )
        return allocation

    def acquire_external_writer_guard(
        self,
        *,
        receipt: LeaseOwnershipReceipt,
        poll_interval_seconds: float = 0.001,
    ) -> AbstractContextManager[None]:
        """按 receipt 固定 byte range 取得 external writer guard。"""

        return acquire_mmap_guard(
            guard_path=receipt.guard_path,
            offset=receipt.writer_guard_offset,
            deadline_ns=receipt.deadline_ns,
            poll_interval_seconds=poll_interval_seconds,
        )

    def write_lease_bytes(
        self,
        *,
        lease: BufferLease,
        content: LocalBufferContent,
    ) -> None:
        """在 writer guard 内把精确内容直接写入 arena extent。"""

        normalized = _normalize_write_content(content)
        if len(normalized) <= 0 or len(normalized) > lease.content_length:
            raise InvalidRequestError(
                "写入长度必须位于预分配 lease 的有效范围内",
                details={
                    "lease_id": lease.lease_id,
                    "reserved_content_length": lease.content_length,
                    "content_length": len(normalized),
                },
            )
        direct_writer = self._get_direct_writer()
        if direct_writer is not None and direct_writer.accepts_lease(lease):
            direct_writer.write_lease_bytes(lease=lease, content=normalized)
            return
        writer = self._writer_locations.get(lease.lease_id)
        if writer is None:
            raise InvalidRequestError("当前 client 不持有 lease writer locator")
        with acquire_mmap_guard(
            guard_path=_require_text(writer, "guard_path"),
            offset=_require_nonnegative_int(writer, "writer_guard_offset"),
            deadline_ns=monotonic_ns()
            + int(self.channel.request_timeout_seconds * 1_000_000_000),
            poll_interval_seconds=0.001,
        ):
            self._mmap_cache.write(
                path=_require_text(writer, "arena_path"),
                offset=lease.offset,
                content=normalized,
                content_length=lease.content_length,
            )

    def commit_buffer(
        self,
        *,
        lease: BufferLease,
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        content_length: int | None = None,
    ) -> LocalBufferWriteResult:
        """发布普通 WRITING lease 为 ACTIVE BufferRef。"""

        payload = self._send_request(
            action="commit-buffer",
            payload={
                "lease": lease.model_dump(mode="json"),
                "media_type": media_type,
                "shape": shape,
                "dtype": dtype,
                "layout": layout,
                "pixel_format": pixel_format,
                "content_length": content_length,
            },
        )
        self._writer_locations.pop(lease.lease_id, None)
        return LocalBufferWriteResult(
            lease=BufferLease.model_validate(_require_dict(payload, "lease")),
            buffer_ref=BufferRef.model_validate(_require_dict(payload, "buffer_ref")),
        )

    def commit_external_buffer(
        self,
        *,
        receipt: LeaseOwnershipReceipt,
        checksum: int,
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
    ) -> LocalBufferWriteResult:
        """校验 external writer 完整性并发布 ACTIVE。"""

        payload = self._send_request(
            action="commit-external-buffer",
            payload={
                "receipt": receipt.model_dump(mode="json"),
                "checksum": checksum,
                "media_type": media_type,
                "shape": shape,
                "dtype": dtype,
                "layout": layout,
                "pixel_format": pixel_format,
            },
        )
        self._writer_locations.pop(receipt.lease_id, None)
        return LocalBufferWriteResult(
            lease=BufferLease.model_validate(_require_dict(payload, "lease")),
            buffer_ref=BufferRef.model_validate(_require_dict(payload, "buffer_ref")),
        )

    def publish_and_transfer_external_buffer(
        self,
        *,
        receipt: LeaseOwnershipReceipt,
        media_type: str,
        new_owner_kind: str,
        new_owner_id: str,
        deadline_ns: int,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
    ) -> ExternalBufferCommitTransferResult:
        """一次 Broker 往返完成 external 发布与首次 owner handoff。"""

        payload = self._send_request(
            action="publish-and-transfer-external-buffer",
            payload={
                "receipt": receipt.model_dump(mode="json"),
                "media_type": media_type,
                "new_owner_kind": new_owner_kind,
                "new_owner_id": new_owner_id,
                "deadline_ns": deadline_ns,
                "shape": shape,
                "dtype": dtype,
                "layout": layout,
                "pixel_format": pixel_format,
            },
        )
        self._writer_locations.pop(receipt.lease_id, None)
        return ExternalBufferCommitTransferResult(
            lease=BufferLease.model_validate(_require_dict(payload, "lease")),
            buffer_ref=BufferRef.model_validate(_require_dict(payload, "buffer_ref")),
            receipt=LeaseOwnershipReceipt.model_validate(
                _require_dict(payload, "receipt")
            ),
        )

    def transfer_lease_ownership(
        self,
        *,
        receipts: tuple[LeaseOwnershipReceipt, ...],
        new_owner_kind: str,
        new_owner_id: str,
        deadline_ns: int,
    ) -> tuple[LeaseOwnershipReceipt, ...]:
        """批量 CAS transfer；任一失效时整批不改变。"""

        payload = self._send_request(
            action="transfer-lease-ownership",
            payload={
                "receipts": [item.model_dump(mode="json") for item in receipts],
                "new_owner_kind": new_owner_kind,
                "new_owner_id": new_owner_id,
                "deadline_ns": deadline_ns,
            },
        )
        raw = payload.get("receipts")
        if not isinstance(raw, list):
            raise ServiceConfigurationError("Broker transfer 返回格式无效")
        return tuple(LeaseOwnershipReceipt.model_validate(item) for item in raw)

    def conditional_release(self, *, receipt: LeaseOwnershipReceipt) -> str:
        """按完整 receipt fence 条件释放。"""

        payload = self._send_request(
            action="conditional-release",
            payload={"receipt": receipt.model_dump(mode="json")},
        )
        status = payload.get("status")
        if not isinstance(status, str):
            raise ServiceConfigurationError("Broker conditional-release 返回格式无效")
        if status in {"released", "stale", "revoking", "quarantined"}:
            self._writer_locations.pop(receipt.lease_id, None)
        return status

    def sweep_reclaiming_leases(self) -> dict[str, int]:
        """推进 REVOKING/QUARANTINED 回收。"""

        payload = self._send_request(action="sweep-reclaiming-leases", payload={})
        return {
            "released_count": int(payload.get("released_count") or 0),
            "quarantined_count": int(payload.get("quarantined_count") or 0),
        }

    def create_frame_channel(
        self,
        *,
        stream_id: str,
        frame_count: int,
        max_frame_content_length: int,
    ) -> dict[str, object]:
        """全有或全无地建立固定 extent frame channel。"""

        payload = self._send_request(
            action="create-frame-channel",
            payload={
                "stream_id": stream_id,
                "frame_count": frame_count,
                "max_frame_content_length": max_frame_content_length,
            },
        )
        return _require_dict(payload, "channel")

    def allocate_frame(
        self,
        *,
        stream_id: str,
        content_length: int,
    ) -> dict[str, object]:
        """申请下一 frame reservation。"""

        payload = self._send_request(
            action="allocate-frame",
            payload={"stream_id": stream_id, "content_length": content_length},
        )
        return _require_dict(payload, "reservation")

    def write_frame(
        self,
        *,
        stream_id: str,
        content: LocalBufferContent,
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FrameRef:
        """在 writer+全部 reader guards 内覆盖 frame extent并发布。"""

        normalized = _normalize_write_content(content)
        reservation = self.allocate_frame(
            stream_id=stream_id,
            content_length=len(normalized),
        )
        guard_path = _require_text(reservation, "guard_path")
        deadline = monotonic_ns() + int(
            self.channel.request_timeout_seconds * 1_000_000_000
        )
        try:
            with acquire_mmap_guard(
                guard_path=guard_path,
                offset=_require_nonnegative_int(reservation, "writer_guard_offset"),
                deadline_ns=deadline,
                poll_interval_seconds=0.001,
            ):
                with acquire_mmap_guard(
                    guard_path=guard_path,
                    offset=_require_nonnegative_int(reservation, "reader_guard_offset"),
                    length=_require_positive_int(reservation, "reader_guard_slots"),
                    deadline_ns=deadline,
                    poll_interval_seconds=0.001,
                ):
                    self._mmap_cache.write(
                        path=_require_text(reservation, "arena_path"),
                        offset=_require_nonnegative_int(reservation, "offset"),
                        content=normalized,
                        content_length=len(normalized),
                    )
            return self.commit_frame(
                reservation=reservation,
                media_type=media_type,
                shape=shape,
                dtype=dtype,
                layout=layout,
                pixel_format=pixel_format,
                metadata=metadata,
            )
        except Exception:
            try:
                self.abort_frame(reservation=reservation)
            except Exception:
                pass
            raise

    def commit_frame(
        self,
        *,
        reservation: dict[str, object],
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FrameRef:
        """发布 frame reservation。"""

        payload = self._send_request(
            action="commit-frame",
            payload={
                "reservation": dict(reservation),
                "media_type": media_type,
                "shape": shape,
                "dtype": dtype,
                "layout": layout,
                "pixel_format": pixel_format,
                "metadata": dict(metadata or {}),
            },
        )
        return FrameRef.model_validate(_require_dict(payload, "frame_ref"))

    def abort_frame(self, *, reservation: dict[str, object]) -> None:
        self._send_request(
            action="abort-frame",
            payload={"reservation": dict(reservation)},
        )

    def destroy_frame_channel(self, *, stream_id: str) -> int:
        payload = self._send_request(
            action="destroy-frame-channel",
            payload={"stream_id": stream_id},
        )
        return _require_nonnegative_int(payload, "released_extent_count")

    def read_buffer_ref(self, buffer_ref: BufferRef) -> bytes:
        """持有 reader guard 时读取精确 content range。"""

        with self.acquire_buffer_ref_view(buffer_ref) as view:
            return bytes(view)

    @contextmanager
    def acquire_buffer_ref_view(self, buffer_ref: BufferRef) -> Iterator[memoryview]:
        """单次 Broker 校验后让 reader guard 覆盖完整零复制消费过程。"""

        direct_reader = self._get_direct_reader()
        if direct_reader is not None and direct_reader.accepts_arena(
            buffer_ref.arena_id
        ):
            with direct_reader.acquire_buffer_ref_view(buffer_ref) as view:
                yield view
            return
        location = self._prepare_buffer_reader(buffer_ref)
        with acquire_mmap_reader_guard(
            guard_path=_require_text(location, "guard_path"),
            start_offset=_require_nonnegative_int(location, "reader_guard_offset"),
            slot_count=_require_positive_int(location, "reader_guard_slots"),
            deadline_ns=monotonic_ns()
            + int(self.channel.request_timeout_seconds * 1_000_000_000),
            poll_interval_seconds=0.001,
        ):
            view = self._mmap_cache.read_view(
                path=_require_text(location, "arena_path"),
                offset=buffer_ref.offset,
                content_length=buffer_ref.content_length,
            )
            try:
                yield view
            finally:
                view.release()

    def read_buffer_ref_view(self, buffer_ref: BufferRef) -> memoryview:
        """返回执行期 owner view；调用方必须在 owner cleanup 前释放。"""

        direct_reader = self._get_direct_reader()
        if direct_reader is not None and direct_reader.accepts_arena(
            buffer_ref.arena_id
        ):
            return direct_reader.read_owned_buffer_ref_view(buffer_ref)
        location = self._prepare_buffer_reader(buffer_ref)
        return self._mmap_cache.read_view(
            path=_require_text(location, "arena_path"),
            offset=buffer_ref.offset,
            content_length=buffer_ref.content_length,
        )

    def acquire_buffer_reader_guard(
        self,
        buffer_ref: BufferRef,
        *,
        deadline_ns: int | None = None,
        poll_interval_seconds: float = 0.001,
    ) -> AbstractContextManager[None]:
        """取得一个 reader byte 后由 Broker 重验 BufferRef。"""

        location = self._prepare_buffer_reader(buffer_ref)
        return acquire_mmap_reader_guard(
            guard_path=_require_text(location, "guard_path"),
            start_offset=_require_nonnegative_int(location, "reader_guard_offset"),
            slot_count=_require_positive_int(location, "reader_guard_slots"),
            deadline_ns=deadline_ns
            or monotonic_ns()
            + int(self.channel.request_timeout_seconds * 1_000_000_000),
            poll_interval_seconds=poll_interval_seconds,
        )

    def read_frame_ref(self, frame_ref: FrameRef) -> bytes:
        with self.acquire_frame_ref_view(frame_ref) as view:
            return bytes(view)

    @contextmanager
    def acquire_frame_ref_view(self, frame_ref: FrameRef) -> Iterator[memoryview]:
        """单次 Broker 校验后让 reader guard 覆盖完整 frame 消费过程。"""

        direct_reader = self._get_direct_reader()
        if direct_reader is not None and direct_reader.accepts_arena(
            frame_ref.arena_id
        ):
            with direct_reader.acquire_frame_ref_view(frame_ref) as view:
                yield view
            return
        location = self._prepare_frame_reader(frame_ref)
        with acquire_mmap_reader_guard(
            guard_path=_require_text(location, "guard_path"),
            start_offset=_require_nonnegative_int(location, "reader_guard_offset"),
            slot_count=_require_positive_int(location, "reader_guard_slots"),
            deadline_ns=monotonic_ns()
            + int(self.channel.request_timeout_seconds * 1_000_000_000),
            poll_interval_seconds=0.001,
        ):
            view = self._mmap_cache.read_view(
                path=_require_text(location, "arena_path"),
                offset=frame_ref.offset,
                content_length=frame_ref.content_length,
            )
            try:
                yield view
            finally:
                view.release()

    def read_frame_ref_view(self, frame_ref: FrameRef) -> memoryview:
        """返回执行期 frame owner view；调用方必须在 owner cleanup 前释放。"""

        direct_reader = self._get_direct_reader()
        if direct_reader is not None and direct_reader.accepts_arena(
            frame_ref.arena_id
        ):
            return direct_reader.read_owned_frame_ref_view(frame_ref)
        location = self._prepare_frame_reader(frame_ref)
        return self._mmap_cache.read_view(
            path=_require_text(location, "arena_path"),
            offset=frame_ref.offset,
            content_length=frame_ref.content_length,
        )

    def acquire_frame_reader_guard(
        self,
        frame_ref: FrameRef,
        *,
        deadline_ns: int | None = None,
        poll_interval_seconds: float = 0.001,
    ) -> AbstractContextManager[None]:
        location = self._prepare_frame_reader(frame_ref)
        return acquire_mmap_reader_guard(
            guard_path=_require_text(location, "guard_path"),
            start_offset=_require_nonnegative_int(location, "reader_guard_offset"),
            slot_count=_require_positive_int(location, "reader_guard_slots"),
            deadline_ns=deadline_ns
            or monotonic_ns()
            + int(self.channel.request_timeout_seconds * 1_000_000_000),
            poll_interval_seconds=poll_interval_seconds,
        )

    def release(self, lease_id: str) -> None:
        self._send_request(action="release", payload={"lease_id": lease_id})
        self._writer_locations.pop(lease_id, None)

    def release_many(self, lease_ids: tuple[str, ...]) -> int:
        """用一条控制消息按给定顺序释放一批 lease。"""

        normalized_ids = tuple(
            lease_id.strip()
            for lease_id in lease_ids
            if isinstance(lease_id, str) and lease_id.strip()
        )
        if not normalized_ids:
            return 0
        payload = self._send_request(
            action="release-many",
            payload={"lease_ids": list(normalized_ids)},
        )
        for lease_id in normalized_ids:
            self._writer_locations.pop(lease_id, None)
        return _require_nonnegative_int(payload, "released_count")

    def release_owner(
        self,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
        owner_id_prefix: str | None = None,
    ) -> int:
        payload = self._send_request(
            action="release-owner",
            payload={
                "owner_kind": owner_kind,
                "owner_id": owner_id,
                "owner_id_prefix": owner_id_prefix,
            },
        )
        return _require_nonnegative_int(payload, "released_count")

    def expire_leases(self) -> int:
        payload = self._send_request(action="expire-leases", payload={})
        return _require_nonnegative_int(payload, "expired_count")

    def shutdown(self) -> None:
        self._send_request(action="shutdown", payload={})

    def close(self) -> None:
        if self._closed:
            return
        # 每个 LocalBufferBrokerClient 独占 supervisor 分配的 event channel。
        # close 必须显式注销路由；否则健康检查、Preview 和短生命周期调用会让
        # router 的 client route 永久增长。关闭通知不等待响应，且不得阻断本地
        # mmap handle 的确定性释放。
        if self.channel.channel_id is not None:
            try:
                self.channel.request_queue.put(
                    {
                        "request_id": f"close-client-channel-{uuid4().hex}",
                        "channel_id": self.channel.channel_id,
                        "action": "__close-client-channel__",
                        "payload": {"channel_id": self.channel.channel_id},
                    }
                )
            except Exception:
                pass
        with self._direct_access_lock:
            if self._direct_reader is not None:
                self._direct_reader.close()
                self._direct_reader = None
            if self._direct_writer is not None:
                self._direct_writer.close()
                self._direct_writer = None
            if self._direct_access is not None:
                self._direct_access.close()
                self._direct_access = None
        self._mmap_cache.close()
        self._writer_locations.clear()
        self._closed = True

    def _ensure_direct_accessors(self) -> None:
        """首次数据面访问时建立一个由 reader/writer 共享的 mmap view。"""

        if self._direct_access_settings is None or self._direct_access is not None:
            return
        with self._direct_access_lock:
            if self._direct_access is not None:
                return
            if self._closed:
                raise InvalidRequestError("LocalBuffer client 已关闭")
            from backend.service.application.local_buffers.direct_mmap_reader import (
                DirectMmapLocalBufferReader,
                DirectMmapLocalBufferWriter,
                open_direct_mmap_local_buffer_access,
            )

            access = open_direct_mmap_local_buffer_access(
                self._direct_access_settings
            )
            try:
                reader = DirectMmapLocalBufferReader(
                    self._direct_access_settings,
                    shared_access=access,
                )
                writer = DirectMmapLocalBufferWriter(
                    self._direct_access_settings,
                    shared_access=access,
                )
            except BaseException:
                access.close()
                raise
            self._direct_access = access
            self._direct_reader = reader
            self._direct_writer = writer

    def _get_direct_reader(self) -> Any | None:
        """返回延迟创建的 direct reader。"""

        self._ensure_direct_accessors()
        return self._direct_reader

    def _get_direct_writer(self) -> Any | None:
        """返回延迟创建的 direct writer。"""

        self._ensure_direct_accessors()
        return self._direct_writer

    def get_health_summary(self) -> dict[str, object]:
        request = snapshot_safe_counter(self._request_count)
        errors = snapshot_safe_counter(self._error_count)
        return {
            "state": "degraded" if errors["value"] else "healthy",
            "request_count": request["value"],
            "request_count_rollover_count": request["rollover_count"],
            "error_count": errors["value"],
            "error_count_rollover_count": errors["rollover_count"],
            "last_error": dict(self._last_error) if self._last_error else None,
        }

    def _prepare_buffer_reader(self, buffer_ref: BufferRef) -> dict[str, object]:
        return self._send_request(
            action="prepare-buffer-reader",
            payload={"buffer_ref": buffer_ref.model_dump(mode="json")},
        )

    def _prepare_frame_reader(self, frame_ref: FrameRef) -> dict[str, object]:
        return self._send_request(
            action="prepare-frame-reader",
            payload={"frame_ref": frame_ref.model_dump(mode="json")},
        )

    def _send_request(
        self,
        *,
        action: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        """串行发送控制请求并严格匹配 response id。"""

        if self._closed:
            raise ServiceConfigurationError("LocalBufferBroker client 已关闭")
        request_id = f"local-buffer-request-{uuid4().hex}"
        message = {
            "request_id": request_id,
            "channel_id": self.channel.channel_id,
            "action": action,
            "payload": payload,
        }
        increment_safe_counter(self._request_count)
        with self._request_response_lock:
            self.channel.request_queue.put(message)
            try:
                response = self.channel.response_queue.get(
                    timeout=self.channel.request_timeout_seconds
                )
            except Empty as error:
                timeout = OperationTimeoutError(
                    "等待 LocalBufferBroker 响应超时",
                    details={"action": action},
                )
                self._record_error(action=action, error=timeout)
                raise timeout from error
        if not isinstance(response, dict) or response.get("request_id") != request_id:
            error = ServiceConfigurationError("LocalBufferBroker 响应 identity 不匹配")
            self._record_error(action=action, error=error)
            raise error
        if not response.get("ok"):
            error_payload = response.get("error")
            details = dict(error_payload) if isinstance(error_payload, dict) else {}
            error_code = str(details.get("code") or "")
            error_details = (
                dict(details.get("details"))
                if isinstance(details.get("details"), dict)
                else {}
            )
            message = str(details.get("message") or "LocalBufferBroker 请求失败")
            if error_code in {
                "local_buffer_capacity_exhausted",
                "local_buffer_contiguous_capacity_exhausted",
            }:
                error = LocalBufferCapacityError(
                    message,
                    contiguous=(
                        error_code
                        == "local_buffer_contiguous_capacity_exhausted"
                    ),
                    details=error_details,
                )
            else:
                error = InvalidRequestError(message, details=error_details)
            self._record_error(action=action, error=error)
            raise error
        result = response.get("payload")
        if not isinstance(result, dict):
            error = ServiceConfigurationError("LocalBufferBroker 响应 payload 无效")
            self._record_error(action=action, error=error)
            raise error
        return dict(result)

    def _record_error(self, *, action: str, error: Exception) -> None:
        increment_safe_counter(self._error_count)
        self._last_error = {
            "action": action,
            "error_type": type(error).__name__,
            "message": str(error),
        }

    def __enter__(self) -> LocalBufferBrokerClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class _MappedFile:
    """保存一个长期 arena 文件 handle 与 mmap。"""

    def __init__(self, path: Path) -> None:
        self.file = path.open("r+b")
        self.view = mmap.mmap(self.file.fileno(), 0)

    def close(self) -> None:
        self.view.close()
        self.file.close()


class _MmapFileCache:
    """按受信 arena path 复用文件 handle，不缓存普通 extent view。"""

    def __init__(self) -> None:
        self._lock = RLock()
        self._files: dict[str, _MappedFile] = {}

    def write(
        self,
        *,
        path: str,
        offset: int,
        content: bytes | memoryview,
        content_length: int,
    ) -> None:
        if len(content) != content_length:
            raise InvalidRequestError("mmap write content length 不一致")
        mapped = self._require_mapped_file(path)
        mapped.view[offset : offset + content_length] = content

    def read_view(
        self,
        *,
        path: str,
        offset: int,
        content_length: int,
    ) -> memoryview:
        mapped = self._require_mapped_file(path)
        return memoryview(mapped.view)[offset : offset + content_length]

    def close(self) -> None:
        with self._lock:
            files = tuple(self._files.items())
        for path, mapped in files:
            mapped.close()
            with self._lock:
                if self._files.get(path) is mapped:
                    self._files.pop(path, None)

    def _require_mapped_file(self, path: str) -> _MappedFile:
        normalized = str(Path(path).resolve())
        with self._lock:
            mapped = self._files.get(normalized)
            if mapped is None:
                mapped = _MappedFile(Path(normalized))
                self._files[normalized] = mapped
            return mapped


def _normalize_write_content(content: LocalBufferContent) -> bytes | memoryview:
    """把 bytes-like 内容规范化为一维连续字节视图。"""

    if isinstance(content, bytes):
        normalized: bytes | memoryview = content
    elif isinstance(content, (bytearray, memoryview)):
        try:
            normalized = memoryview(content).cast("B")
        except TypeError as error:
            raise InvalidRequestError("写入内容必须是连续 buffer") from error
    else:
        raise InvalidRequestError("写入内容必须支持 buffer protocol")
    if len(normalized) <= 0:
        raise InvalidRequestError("写入内容不能为空")
    return normalized


def _require_dict(payload: dict[str, object], field_name: str) -> dict[str, object]:
    value = payload.get(field_name)
    if not isinstance(value, dict):
        raise ServiceConfigurationError(f"Broker payload 缺少 {field_name}")
    return dict(value)


def _require_text(payload: dict[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ServiceConfigurationError(f"Broker payload 缺少 {field_name}")
    return value.strip()


def _require_nonnegative_int(payload: dict[str, object], field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ServiceConfigurationError(f"Broker payload {field_name} 不是非负整数")
    return value


def _require_positive_int(payload: dict[str, object], field_name: str) -> int:
    value = _require_nonnegative_int(payload, field_name)
    if value <= 0:
        raise ServiceConfigurationError(f"Broker payload {field_name} 必须大于 0")
    return value
