"""把固定 mmap arena 封装为 LocalBufferBroker 的业务 lease API。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from time import monotonic_ns

from backend.contracts.buffers import BufferLease, BufferRef, FrameRef
from backend.contracts.buffers.lease_ownership import (
    ExternalBufferAllocation,
    LeaseOwnershipReceipt,
)
from backend.service.application.errors import (
    InvalidRequestError,
    LocalBufferCapacityError,
    ServiceConfigurationError,
)
from backend.service.infrastructure.ipc.mmap_primitives import crc32_ieee
from backend.service.infrastructure.local_buffers.buddy_allocator import (
    BuddyAllocationError,
)
from backend.service.infrastructure.local_buffers.mmap_buffer_arena import (
    ArenaLeaseReceipt,
    LocalBufferArenaError,
    LocalBufferArenaIntegrityError,
    MmapBufferArena,
    MmapBufferArenaConfig,
)


@dataclass(frozen=True, slots=True)
class LocalBufferWriteResult:
    """描述一次普通或 external buffer 发布结果。"""

    lease: BufferLease
    buffer_ref: BufferRef


@dataclass(frozen=True, slots=True)
class ExternalBufferCommitTransferResult:
    """描述 external buffer 发布与首次 owner handoff 结果。"""

    lease: BufferLease
    buffer_ref: BufferRef
    receipt: LeaseOwnershipReceipt


@dataclass(slots=True)
class _LeaseRecord:
    """保存 broker 进程内可变业务元数据；权威 extent identity 位于 descriptor。"""

    low_receipt: ArenaLeaseReceipt
    lease: BufferLease
    media_type: str | None = None
    shape: tuple[int, ...] = ()
    dtype: str | None = None
    layout: str | None = None
    pixel_format: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class _FrameChannel:
    """保存 frame channel 的长期 extent reservation 与发布游标。"""

    stream_id: str
    receipts: tuple[ArenaLeaseReceipt, ...]
    max_frame_content_length: int
    next_position: int = 0
    next_sequence_id: int = 0
    frames: dict[int, FrameRef] = field(default_factory=dict)


class LocalBufferArenaPool:
    """LocalBufferBroker 单一固定 arena 的上层 lease 与 frame 状态机。"""

    def __init__(self, config: MmapBufferArenaConfig) -> None:
        """创建 arena 并初始化当前 epoch 的进程内记录。"""

        self.config = config
        self.arena = MmapBufferArena(config)
        self.arena_id = config.arena_id
        self.broker_epoch = self.arena.broker_epoch
        self._lock = RLock()
        self._records: dict[str, _LeaseRecord] = {}
        self._channels: dict[str, _FrameChannel] = {}
        self._stale_fence_count = 0

    def allocate(
        self,
        *,
        content_length: int,
        owner_kind: str,
        owner_id: str,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
        deadline_ns: int | None = None,
    ) -> BufferLease:
        """按 content length 动态分配最小连续 extent。"""

        created_at = datetime.now(timezone.utc)
        expires_at = (
            created_at + timedelta(seconds=ttl_seconds)
            if ttl_seconds is not None
            else None
        )
        effective_deadline = deadline_ns or _deadline_from_ttl(ttl_seconds)
        try:
            low_receipt = self.arena.allocate(
                content_length=content_length,
                deadline_ns=effective_deadline,
            )
        except BuddyAllocationError as error:
            raise _build_capacity_error(error) from error
        except LocalBufferArenaIntegrityError as error:
            raise ServiceConfigurationError(str(error)) from error
        except (LocalBufferArenaError, ValueError) as error:
            raise InvalidRequestError(str(error)) from error
        lease_id = f"lease-{low_receipt.lease_token.hex()}"
        lease = BufferLease(
            lease_id=lease_id,
            buffer_id=f"{self.arena_id}:{low_receipt.descriptor_index}",
            owner_kind=_require_text(owner_kind, "owner_kind"),
            owner_id=_require_text(owner_id, "owner_id"),
            arena_id=self.arena_id,
            descriptor_index=low_receipt.descriptor_index,
            descriptor_generation=low_receipt.descriptor_generation,
            broker_epoch=self.broker_epoch,
            offset=low_receipt.offset,
            content_length=content_length,
            allocation_capacity_bytes=low_receipt.allocation_capacity_bytes,
            created_at=created_at,
            expires_at=expires_at,
            state="writing",
            trace_id=trace_id,
        )
        with self._lock:
            self._records[lease_id] = _LeaseRecord(
                low_receipt=low_receipt,
                lease=lease,
            )
        return lease

    def allocate_external(
        self,
        *,
        content_length: int,
        owner_kind: str,
        owner_id: str,
        deadline_ns: int,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> ExternalBufferAllocation:
        """为可信本机 writer 返回公开 lease 与服务端私有 receipt。"""

        lease = self.allocate(
            content_length=content_length,
            owner_kind=owner_kind,
            owner_id=owner_id,
            ttl_seconds=ttl_seconds,
            trace_id=trace_id,
            deadline_ns=deadline_ns,
        )
        record = self._require_record(lease.lease_id)
        receipt = self._build_receipt(record)
        return ExternalBufferAllocation(
            lease=lease,
            receipt=receipt,
            allocation_capacity_bytes=lease.allocation_capacity_bytes,
        )

    def write_lease_bytes(self, *, lease: BufferLease, content: memoryview) -> None:
        """在 writer guard 与 descriptor 重验后写入精确 extent。"""

        record = self._require_lease(lease, expected_states={"writing"})
        if content.nbytes <= 0 or content.nbytes > lease.content_length:
            raise InvalidRequestError("写入长度超出 lease 预留范围")
        try:
            with self.arena.acquire_writer_view(record.low_receipt) as view:
                view[: content.nbytes] = content
        except LocalBufferArenaError as error:
            raise InvalidRequestError(str(error)) from error

    def commit_lease(
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
        """把 writing lease 发布为 ACTIVE BufferRef。"""

        record = self._require_lease(lease, expected_states={"writing"})
        try:
            if content_length is not None:
                record.low_receipt = self.arena.resize_writing_content(
                    record.low_receipt,
                    content_length=content_length,
                )
                record.lease = record.lease.model_copy(
                    update={"content_length": content_length}
                )
            self.arena.publish_active(record.low_receipt)
        except LocalBufferArenaError as error:
            raise InvalidRequestError(str(error)) from error
        with self._lock:
            record.lease = record.lease.model_copy(update={"state": "active"})
            record.media_type = _require_text(media_type, "media_type")
            record.shape = tuple(shape)
            record.dtype = _optional_text(dtype)
            record.layout = _optional_text(layout)
            record.pixel_format = _optional_text(pixel_format)
            return LocalBufferWriteResult(
                lease=record.lease,
                buffer_ref=self._build_buffer_ref(record),
            )

    def commit_external_lease(
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
        """确认 external guard 已释放、校验 CRC 后发布 ACTIVE。"""

        record = self._require_receipt(receipt, expected_states={"writing"})
        try:
            with self.arena.acquire_writer_view(record.low_receipt) as view:
                actual = crc32_ieee(view)
        except LocalBufferArenaError as error:
            raise InvalidRequestError(str(error)) from error
        if actual != checksum:
            raise InvalidRequestError(
                "external LocalBuffer checksum 校验失败",
                details={"expected_checksum": checksum, "actual_checksum": actual},
            )
        return self.commit_lease(
            lease=record.lease,
            media_type=media_type,
            shape=shape,
            dtype=dtype,
            layout=layout,
            pixel_format=pixel_format,
        )

    def publish_external_lease_and_transfer(
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
        """在 writer publication barrier 内发布并执行第一次 owner handoff。"""

        record = self._require_receipt(receipt, expected_states={"writing"})
        owner_kind = _require_text(new_owner_kind, "new_owner_kind")
        owner_id = _require_text(new_owner_id, "new_owner_id")
        try:
            low_receipt = self.arena.publish_external_active_and_transfer(
                record.low_receipt,
                new_deadline_ns=deadline_ns,
            )
        except LocalBufferArenaError as error:
            raise InvalidRequestError(str(error)) from error
        with self._lock:
            record.low_receipt = low_receipt
            record.lease = record.lease.model_copy(
                update={
                    "state": "active",
                    "owner_kind": owner_kind,
                    "owner_id": owner_id,
                }
            )
            record.media_type = _require_text(media_type, "media_type")
            record.shape = tuple(shape)
            record.dtype = _optional_text(dtype)
            record.layout = _optional_text(layout)
            record.pixel_format = _optional_text(pixel_format)
            transferred = self._build_receipt(record)
        return ExternalBufferCommitTransferResult(
            lease=record.lease,
            buffer_ref=self._build_buffer_ref(record),
            receipt=transferred,
        )

    def transfer_ownership_batch(
        self,
        *,
        receipts: tuple[LeaseOwnershipReceipt, ...],
        new_owner_kind: str,
        new_owner_id: str,
        deadline_ns: int,
    ) -> tuple[LeaseOwnershipReceipt, ...]:
        """全量校验后批量 CAS owner/deadline。"""

        records = [
            self._require_receipt(item, expected_states={"writing", "active"})
            for item in receipts
        ]
        try:
            low_receipts = self.arena.transfer_owners_batch(
                tuple(item.low_receipt for item in records),
                new_deadline_ns=deadline_ns,
            )
        except LocalBufferArenaError as error:
            raise InvalidRequestError(str(error)) from error
        owner_kind = _require_text(new_owner_kind, "new_owner_kind")
        owner_id = _require_text(new_owner_id, "new_owner_id")
        with self._lock:
            for record, low_receipt in zip(records, low_receipts, strict=True):
                record.low_receipt = low_receipt
                record.lease = record.lease.model_copy(
                    update={"owner_kind": owner_kind, "owner_id": owner_id}
                )
            return tuple(self._build_receipt(item) for item in records)

    def validate_ownership_batch(
        self,
        *,
        receipts: tuple[LeaseOwnershipReceipt, ...],
        expected_states: set[str] | None = None,
    ) -> None:
        """只读验证整批 receipt。"""

        for receipt in receipts:
            self._require_receipt(
                receipt,
                expected_states=expected_states or {"active"},
            )

    def conditional_release(self, *, receipt: LeaseOwnershipReceipt) -> str:
        """按完整 identity 请求回收；旧 receipt 只返回 stale。"""

        try:
            record = self._require_receipt(
                receipt,
                expected_states={
                    "writing",
                    "active",
                    "revoking",
                    "quarantined",
                },
            )
        except InvalidRequestError:
            with self._lock:
                self._stale_fence_count += 1
            return "stale"
        result = self.arena.request_reclaim(record.low_receipt)
        with self._lock:
            if result == "released":
                self._records.pop(record.lease.lease_id, None)
            elif result in {"revoking", "quarantined"}:
                record.lease = record.lease.model_copy(update={"state": result})
        return result

    def release(self, lease_id: str) -> None:
        """释放当前 epoch 指定 lease。"""

        record = self._require_record(lease_id)
        result = self.arena.request_reclaim(record.low_receipt)
        with self._lock:
            if result == "released":
                self._records.pop(lease_id, None)
            else:
                record.lease = record.lease.model_copy(update={"state": result})

    def release_owner(
        self,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
        owner_id_prefix: str | None = None,
    ) -> int:
        """回收匹配 owner 的全部普通 lease。"""

        if owner_id is None and owner_id_prefix is None:
            raise InvalidRequestError("release_owner 必须提供 owner_id 或 owner_id_prefix")
        with self._lock:
            candidates = [
                item
                for item in self._records.values()
                if (owner_kind is None or item.lease.owner_kind == owner_kind)
                and (owner_id is None or item.lease.owner_id == owner_id)
                and (
                    owner_id_prefix is None
                    or item.lease.owner_id.startswith(owner_id_prefix)
                )
            ]
        released = 0
        for record in candidates:
            result = self.conditional_release(receipt=self._build_receipt(record))
            released += int(result == "released")
        return released

    def expire_leases(self, *, now: datetime | None = None) -> int:
        """按 wall-clock expires_at 请求回收过期 lease。"""

        current = now or datetime.now(timezone.utc)
        with self._lock:
            expired = [
                item
                for item in self._records.values()
                if item.lease.expires_at is not None
                and item.lease.expires_at <= current
            ]
        return sum(
            self.conditional_release(receipt=self._build_receipt(item)) == "released"
            for item in expired
        )

    def sweep_reclaiming_leases(
        self,
        *,
        now_ns: int | None = None,
    ) -> dict[str, int]:
        """推进底层到期/revoking descriptor并同步进程内记录。"""

        summary = self.arena.sweep(now_ns=now_ns)
        with self._lock:
            stale_ids = []
            for lease_id, record in self._records.items():
                try:
                    snapshot = self.arena.descriptor_snapshot(
                        record.low_receipt.descriptor_index
                    )
                except LocalBufferArenaError:
                    stale_ids.append(lease_id)
                    continue
                if (
                    snapshot.state == "free"
                    or snapshot.descriptor_generation
                    != record.low_receipt.descriptor_generation
                ):
                    stale_ids.append(lease_id)
                elif snapshot.state in {"revoking", "quarantined"}:
                    record.lease = record.lease.model_copy(
                        update={"state": snapshot.state}
                    )
            for lease_id in stale_ids:
                self._records.pop(lease_id, None)
        return summary

    def validate_buffer_ref(self, buffer_ref: BufferRef) -> None:
        """验证 BufferRef 仍指向当前 ACTIVE extent。"""

        record = self._require_record(buffer_ref.lease_id)
        if buffer_ref != self._build_buffer_ref(record):
            raise InvalidRequestError("BufferRef identity 或表示元数据不匹配")
        try:
            self.arena.validate_receipt(
                record.low_receipt,
                expected_states={"active"},
            )
        except LocalBufferArenaError as error:
            raise InvalidRequestError(str(error)) from error

    def read_buffer_ref(self, buffer_ref: BufferRef) -> bytes:
        """在 reader guard 生命周期内复制出明确请求的 bytes。"""

        self.validate_buffer_ref(buffer_ref)
        record = self._require_record(buffer_ref.lease_id)
        try:
            with self.arena.acquire_reader_view(record.low_receipt) as view:
                return bytes(view[: buffer_ref.content_length])
        except LocalBufferArenaError as error:
            raise InvalidRequestError(str(error)) from error

    def reader_guard_location(self, buffer_ref: BufferRef) -> dict[str, object]:
        """校验引用后返回受信 guard byte range。"""

        self.validate_buffer_ref(buffer_ref)
        return self.arena.guard_location(buffer_ref.descriptor_index)

    def create_frame_channel(
        self,
        *,
        stream_id: str,
        frame_count: int,
        max_frame_content_length: int,
    ) -> dict[str, object]:
        """全有或全无地建立长期连续 extent channel。"""

        stream = _require_text(stream_id, "stream_id")
        with self._lock:
            if stream in self._channels:
                raise InvalidRequestError("frame channel 已存在")
        try:
            receipts = self.arena.allocate_frame_channel(
                frame_count=frame_count,
                max_frame_content_length=max_frame_content_length,
                deadline_ns=(1 << 63) - 1,
            )
        except BuddyAllocationError as error:
            raise _build_capacity_error(error) from error
        except LocalBufferArenaIntegrityError as error:
            raise ServiceConfigurationError(str(error)) from error
        except (LocalBufferArenaError, ValueError) as error:
            raise InvalidRequestError(str(error)) from error
        channel = _FrameChannel(
            stream_id=stream,
            receipts=receipts,
            max_frame_content_length=max_frame_content_length,
        )
        with self._lock:
            self._channels[stream] = channel
        return self._build_channel_status(channel)

    def allocate_frame(self, *, stream_id: str, content_length: int) -> dict[str, object]:
        """选择 channel 下一 extent 并返回实际 frame 写入 reservation。"""

        with self._lock:
            channel = self._require_channel(stream_id)
            if content_length <= 0 or content_length > channel.max_frame_content_length:
                raise InvalidRequestError("frame content length 超过 channel 上限")
            position = channel.next_position
            receipt = channel.receipts[position]
            try:
                receipt = self.arena.begin_frame_write(receipt)
            except LocalBufferArenaError as error:
                raise InvalidRequestError(str(error)) from error
            receipts = list(channel.receipts)
            receipts[position] = receipt
            channel.receipts = tuple(receipts)
            channel.frames.pop(receipt.descriptor_index, None)
            sequence_id = channel.next_sequence_id
            channel.next_position = (position + 1) % len(channel.receipts)
            channel.next_sequence_id += 1
        return {
            "stream_id": channel.stream_id,
            "sequence_id": sequence_id,
            "arena_id": self.arena_id,
            "descriptor_index": receipt.descriptor_index,
            "descriptor_generation": receipt.descriptor_generation,
            "broker_epoch": self.broker_epoch,
            "buffer_id": f"{self.arena_id}:frame:{channel.stream_id}:{receipt.descriptor_index}",
            "offset": receipt.offset,
            "content_length": content_length,
            "allocation_capacity_bytes": receipt.allocation_capacity_bytes,
            **self.arena.guard_location(receipt.descriptor_index),
        }

    def write_frame_bytes(
        self,
        *,
        reservation: dict[str, object],
        content: memoryview,
    ) -> None:
        """覆盖 frame 前同时持有 writer 和全部 reader guards。"""

        receipt = self._frame_receipt(reservation)
        content_length = _payload_int(reservation, "content_length")
        if content.nbytes != content_length:
            raise InvalidRequestError("frame 写入长度与 reservation 不一致")
        self.arena.write_frame_bytes(receipt, content=content)

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
        """发布当前 sequence 的 FrameRef；旧 sequence 随后失效。"""

        receipt = self._frame_receipt(reservation)
        stream_id = _payload_text(reservation, "stream_id")
        sequence_id = _payload_int(reservation, "sequence_id")
        content_length = _payload_int(reservation, "content_length")
        frame_ref = FrameRef(
            stream_id=stream_id,
            sequence_id=sequence_id,
            buffer_id=_payload_text(reservation, "buffer_id"),
            arena_id=self.arena_id,
            descriptor_index=receipt.descriptor_index,
            descriptor_generation=receipt.descriptor_generation,
            broker_epoch=self.broker_epoch,
            offset=receipt.offset,
            content_length=content_length,
            allocation_capacity_bytes=receipt.allocation_capacity_bytes,
            shape=shape,
            dtype=_optional_text(dtype),
            layout=_optional_text(layout),
            pixel_format=_optional_text(pixel_format),
            media_type=_require_text(media_type, "media_type"),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            channel = self._require_channel(stream_id)
            channel.frames[receipt.descriptor_index] = frame_ref
        return frame_ref

    def abort_frame(self, *, reservation: dict[str, object]) -> None:
        """reservation 尚未发布时无需改变长期 extent。"""

        self._frame_receipt(reservation)

    def validate_frame_ref(self, frame_ref: FrameRef) -> None:
        """拒绝已被 ring wrap 覆盖的旧 sequence。"""

        with self._lock:
            channel = self._require_channel(frame_ref.stream_id)
            current = channel.frames.get(frame_ref.descriptor_index)
            if current != frame_ref:
                raise InvalidRequestError("FrameRef 已被覆盖或 identity 不匹配")
            receipt = next(
                (
                    item
                    for item in channel.receipts
                    if item.descriptor_index == frame_ref.descriptor_index
                ),
                None,
            )
        if receipt is None:
            raise InvalidRequestError("FrameRef descriptor 不属于 channel")
        self.arena.validate_receipt(receipt, expected_states={"frame_reserved"})

    def read_frame_ref(self, frame_ref: FrameRef) -> bytes:
        """在 reader guard 内读取当前 frame 有效 bytes。"""

        self.validate_frame_ref(frame_ref)
        receipt = self._channel_receipt(
            frame_ref.stream_id,
            frame_ref.descriptor_index,
        )
        with self.arena.acquire_reader_view(receipt) as view:
            return bytes(view[: frame_ref.content_length])

    def frame_reader_guard_location(self, frame_ref: FrameRef) -> dict[str, object]:
        """验证 frame 后返回受信 reader guard range。"""

        self.validate_frame_ref(frame_ref)
        return self.arena.guard_location(frame_ref.descriptor_index)

    def destroy_frame_channel(self, *, stream_id: str) -> int:
        """销毁 channel；仍被 reader 使用的 extent 进入 REVOKING。"""

        with self._lock:
            channel = self._channels.pop(stream_id, None)
        if channel is None:
            raise InvalidRequestError("frame channel 不存在")
        self.arena.destroy_frame_channel(channel.receipts)
        return len(channel.receipts)

    def build_status(self) -> dict[str, object]:
        """合并 arena 守恒指标和有限 channel 摘要。"""

        status = self.arena.build_status()
        with self._lock:
            status["active_lease_count"] = len(self._records)
            status["frame_channel_count"] = len(self._channels)
            status["stale_fence_count"] = self._stale_fence_count
            status["frame_channels"] = [
                self._build_channel_status(item) for item in self._channels.values()
            ]
        return status

    def close(self) -> None:
        """关闭固定 arena。"""

        self.arena.close()

    def __enter__(self) -> LocalBufferArenaPool:
        """允许测试和独立 owner 使用确定性的上下文生命周期。"""

        return self

    def __exit__(self, *_args: object) -> None:
        """离开上下文时关闭 mmap 与 owner lock。"""

        self.close()

    def _require_record(self, lease_id: str) -> _LeaseRecord:
        with self._lock:
            record = self._records.get(_require_text(lease_id, "lease_id"))
        if record is None:
            raise InvalidRequestError("LocalBuffer lease 不存在")
        return record

    def _require_lease(
        self,
        lease: BufferLease,
        *,
        expected_states: set[str],
    ) -> _LeaseRecord:
        record = self._require_record(lease.lease_id)
        if record.lease != lease or record.lease.state not in expected_states:
            raise InvalidRequestError("LocalBuffer lease identity 或状态不匹配")
        return record

    def _require_receipt(
        self,
        receipt: LeaseOwnershipReceipt,
        *,
        expected_states: set[str],
    ) -> _LeaseRecord:
        record = self._require_record(receipt.lease_id)
        if self._build_receipt(record) != receipt or record.lease.state not in expected_states:
            raise InvalidRequestError("LocalBuffer ownership receipt 已失效")
        return record

    def _build_receipt(self, record: _LeaseRecord) -> LeaseOwnershipReceipt:
        low = record.low_receipt
        guard = self.arena.guard_location(low.descriptor_index)
        return LeaseOwnershipReceipt(
            arena_id=self.arena_id,
            descriptor_index=low.descriptor_index,
            descriptor_generation=low.descriptor_generation,
            broker_epoch=self.broker_epoch,
            lease_id=record.lease.lease_id,
            buffer_id=record.lease.buffer_id,
            lease_token=low.lease_token.hex(),
            owner_token=low.owner_token.hex(),
            owner_kind=record.lease.owner_kind,
            owner_id=record.lease.owner_id,
            deadline_ns=low.deadline_ns,
            offset=low.offset,
            content_length=low.content_length,
            allocation_capacity_bytes=low.allocation_capacity_bytes,
            layout_fingerprint=self.arena.layout_fingerprint.hex(),
            guard_path=str(guard["guard_path"]),
            publication_guard_offset=int(guard["publication_guard_offset"]),
            writer_guard_offset=int(guard["writer_guard_offset"]),
            reader_guard_offset=int(guard["reader_guard_offset"]),
            reader_guard_slots=int(guard["reader_guard_slots"]),
        )

    def _build_buffer_ref(self, record: _LeaseRecord) -> BufferRef:
        lease = record.lease
        if record.media_type is None:
            raise InvalidRequestError("ACTIVE LocalBuffer 缺少 media_type")
        return BufferRef(
            buffer_id=lease.buffer_id,
            lease_id=lease.lease_id,
            arena_id=lease.arena_id,
            descriptor_index=lease.descriptor_index,
            descriptor_generation=lease.descriptor_generation,
            broker_epoch=lease.broker_epoch,
            offset=lease.offset,
            content_length=lease.content_length,
            allocation_capacity_bytes=lease.allocation_capacity_bytes,
            shape=record.shape,
            dtype=record.dtype,
            layout=record.layout,
            pixel_format=record.pixel_format,
            media_type=record.media_type,
            readonly=True,
            metadata=dict(record.metadata),
        )

    def _require_channel(self, stream_id: str) -> _FrameChannel:
        channel = self._channels.get(_require_text(stream_id, "stream_id"))
        if channel is None:
            raise InvalidRequestError("frame channel 不存在")
        return channel

    def _channel_receipt(
        self,
        stream_id: str,
        descriptor_index: int,
    ) -> ArenaLeaseReceipt:
        with self._lock:
            channel = self._require_channel(stream_id)
            receipt = next(
                (
                    item
                    for item in channel.receipts
                    if item.descriptor_index == descriptor_index
                ),
                None,
            )
        if receipt is None:
            raise InvalidRequestError("frame descriptor 不属于 channel")
        return receipt

    def _frame_receipt(self, reservation: dict[str, object]) -> ArenaLeaseReceipt:
        stream_id = _payload_text(reservation, "stream_id")
        descriptor_index = _payload_int(reservation, "descriptor_index")
        receipt = self._channel_receipt(stream_id, descriptor_index)
        if (
            _payload_text(reservation, "arena_id") != self.arena_id
            or _payload_text(reservation, "broker_epoch") != self.broker_epoch
            or _payload_int(reservation, "descriptor_generation")
            != receipt.descriptor_generation
            or _payload_int(reservation, "offset") != receipt.offset
            or _payload_int(reservation, "allocation_capacity_bytes")
            != receipt.allocation_capacity_bytes
        ):
            raise InvalidRequestError("frame reservation identity 不匹配")
        return receipt

    @staticmethod
    def _build_channel_status(channel: _FrameChannel) -> dict[str, object]:
        return {
            "stream_id": channel.stream_id,
            "frame_count": len(channel.receipts),
            "max_frame_content_length": channel.max_frame_content_length,
            "descriptor_indices": [item.descriptor_index for item in channel.receipts],
            "next_position": channel.next_position,
            "next_sequence_id": channel.next_sequence_id,
        }


def _deadline_from_ttl(ttl_seconds: float | None) -> int:
    """把可选 TTL 转为后端 monotonic deadline。"""

    if ttl_seconds is None:
        return (1 << 63) - 1
    if ttl_seconds <= 0:
        raise InvalidRequestError("ttl_seconds 必须大于 0")
    return monotonic_ns() + int(ttl_seconds * 1_000_000_000)


def _build_capacity_error(
    error: BuddyAllocationError,
) -> LocalBufferCapacityError | ServiceConfigurationError:
    """把 allocator 分类错误转换为稳定服务错误，不误报为配置失败。"""

    if error.kind == "integrity":
        return ServiceConfigurationError(
            "LocalBuffer allocator 完整性校验失败",
            details={"failure_kind": error.kind, "error_message": str(error)},
        )
    return LocalBufferCapacityError(
        str(error),
        contiguous=error.kind == "contiguous_capacity",
        details={"failure_kind": error.kind},
    )


def _require_text(value: str, field_name: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise InvalidRequestError(f"{field_name} 不能为空")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _payload_text(payload: dict[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{field_name} 不能为空")
    return value.strip()


def _payload_int(payload: dict[str, object], field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise InvalidRequestError(f"{field_name} 必须是非负整数")
    return value
