"""file-backed mmap buffer pool 的最小实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import mmap
from pathlib import Path
from threading import Lock
from uuid import uuid4

from backend.contracts.buffers import BufferLease, BufferRef, FrameRef
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.safe_counter import (
    SafeCounterState,
    increment_safe_counter,
    snapshot_safe_counter,
)


@dataclass(frozen=True)
class MmapBufferPoolConfig:
    """描述 mmap buffer pool 的固定配置。

    字段：
    - pool_name：pool 名称。
    - root_dir：mmap 文件所在目录。
    - file_size_bytes：单个 mmap 文件总容量。
    - slot_size_bytes：固定槽位容量。
    - file_name：mmap 文件名。
    - broker_epoch：broker 启动代次；未提供时自动生成。
    """

    pool_name: str
    root_dir: Path
    file_size_bytes: int
    slot_size_bytes: int
    file_name: str = "pool-001.dat"
    broker_epoch: str | None = None


@dataclass(frozen=True)
class MmapBufferWriteResult:
    """描述一次 mmap 写入结果。

    字段：
    - lease：写入完成后处于 active 状态的 lease。
    - buffer_ref：可传递给读取方的 BufferRef。
    """

    lease: BufferLease
    buffer_ref: BufferRef


@dataclass
class _SlotState:
    """描述单个固定槽位的运行时状态。

    字段：
    - generation：槽位复用代次。
    - lease：普通 BufferLease 占用状态。
    - frame：ring buffer 帧占用或预留状态。
    """

    generation: int = 0
    lease: BufferLease | None = None
    frame: "_FrameSlotState | None" = None


@dataclass
class _FrameSlotState:
    """描述 ring buffer 单个帧槽位的运行时状态。

    字段：
    - stream_id：所属连续帧来源 id。
    - sequence_id：当前帧序号；预留槽位为 -1。
    - buffer_id：FrameRef 使用的槽位 id。
    - offset：帧槽位在 mmap 文件中的起始偏移。
    - size：当前帧有效字节数。
    - generation：槽位复用代次。
    - state：帧槽位状态，支持 reserved、writing 和 active。
    - media_type：当前帧媒体类型。
    - shape：raw 图像或 tensor 形状。
    - dtype：raw 数据类型。
    - layout：raw 数据布局。
    - pixel_format：像素格式。
    - metadata：附加元数据。
    """

    stream_id: str
    sequence_id: int
    buffer_id: str
    offset: int
    size: int = 0
    generation: int = 0
    state: str = "reserved"
    media_type: str | None = None
    shape: tuple[int, ...] = ()
    dtype: str | None = None
    layout: str | None = None
    pixel_format: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class _RingChannelState:
    """描述一个 ring buffer channel 的运行时状态。

    字段：
    - stream_id：连续帧来源 id。
    - slot_indices：该 channel 预留的 pool 槽位索引。
    - next_slot_position：下一次写入使用的 slot_indices 位置。
    - next_sequence_id：下一帧序号。
    - published_frame_count：已发布帧数量计数器状态。
    - overwritten_frame_count：覆盖旧 active 帧数量计数器状态。
    """

    stream_id: str
    slot_indices: tuple[int, ...]
    next_slot_position: int = 0
    next_sequence_id: int = 0
    published_frame_count: SafeCounterState = field(default_factory=SafeCounterState)
    overwritten_frame_count: SafeCounterState = field(default_factory=SafeCounterState)


class MmapBufferPool:
    """管理一个固定容量 file-backed mmap 文件池。"""

    def __init__(self, config: MmapBufferPoolConfig) -> None:
        """初始化 mmap pool 并创建固定大小文件。

        参数：
        - config：mmap pool 固定配置。
        """

        self.config = _validate_config(config)
        self.pool_name = self.config.pool_name.strip()
        self.broker_epoch = self.config.broker_epoch or f"epoch-{uuid4().hex}"
        self.file_path = self.config.root_dir / self.config.file_name
        self._slot_count = self.config.file_size_bytes // self.config.slot_size_bytes
        self._slots: list[_SlotState] = [_SlotState() for _ in range(self._slot_count)]
        self._ring_channels: dict[str, _RingChannelState] = {}
        self._lock = Lock()
        self._closed = False
        self._allocation_count = SafeCounterState()
        self._allocation_failure_count = SafeCounterState()
        self._pool_full_count = SafeCounterState()
        self._released_count = SafeCounterState()
        self._expired_count = SafeCounterState()
        self._max_used_count = 0
        self._frame_channel_count = SafeCounterState()
        self._frame_write_count = SafeCounterState()
        self._frame_overwrite_count = SafeCounterState()

        file_handle = None
        try:
            self.config.root_dir.mkdir(parents=True, exist_ok=True)
            with self.file_path.open("wb") as pool_file:
                pool_file.truncate(self.config.file_size_bytes)
            file_handle = self.file_path.open("r+b")
            self._mmap = mmap.mmap(file_handle.fileno(), self.config.file_size_bytes)
        except OSError as exc:
            if file_handle is not None:
                try:
                    file_handle.close()
                except OSError:
                    pass
            raise ServiceConfigurationError(
                "初始化 mmap buffer pool 文件失败",
                details={
                    "pool_name": self.pool_name,
                    "file_path": str(self.file_path),
                    "file_size_bytes": self.config.file_size_bytes,
                    "slot_size_bytes": self.config.slot_size_bytes,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc) or type(exc).__name__,
                },
            ) from exc
        self._file = file_handle

    @property
    def capacity_bytes(self) -> int:
        """返回 pool 总容量。"""

        return self.config.file_size_bytes

    @property
    def slot_count(self) -> int:
        """返回固定槽位数量。"""

        return self._slot_count

    def allocate(
        self,
        *,
        size: int,
        owner_kind: str,
        owner_id: str,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> BufferLease:
        """分配一个固定槽位并返回 writing 状态 lease。

        参数：
        - size：本次 lease 需要写入的有效字节数。
        - owner_kind：租约拥有者类型。
        - owner_id：租约拥有者实例 id。
        - ttl_seconds：可选过期秒数。
        - trace_id：链路追踪 id。

        返回：
        - BufferLease：writing 状态 lease。
        """

        self._ensure_open()
        _validate_size(size, self.config.slot_size_bytes)
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise InvalidRequestError("mmap buffer lease ttl_seconds 必须大于 0")
        normalized_owner_kind = _require_stripped_text(owner_kind, "owner_kind")
        normalized_owner_id = _require_stripped_text(owner_id, "owner_id")
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None
        with self._lock:
            try:
                slot_index = self._find_free_slot_index()
            except InvalidRequestError:
                increment_safe_counter(self._allocation_failure_count)
                increment_safe_counter(self._pool_full_count)
                raise
            slot_state = self._slots[slot_index]
            slot_state.generation += 1
            lease = BufferLease(
                lease_id=f"lease-{uuid4().hex}",
                buffer_id=self._build_buffer_id(slot_index),
                owner_kind=normalized_owner_kind,
                owner_id=normalized_owner_id,
                pool_name=self.pool_name,
                file_path=str(self.file_path),
                offset=slot_index * self.config.slot_size_bytes,
                size=size,
                created_at=created_at,
                expires_at=expires_at,
                ref_count=1,
                state="writing",
                trace_id=_normalize_optional_text(trace_id),
                broker_epoch=self.broker_epoch,
                generation=slot_state.generation,
            )
            slot_state.lease = lease
            increment_safe_counter(self._allocation_count)
            self._max_used_count = max(self._max_used_count, self._count_used_slots_locked())
            return lease

    def write_lease(
        self,
        *,
        lease: BufferLease,
        content: bytes,
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        readonly: bool = True,
    ) -> MmapBufferWriteResult:
        """向 writing lease 写入字节并发布为 active BufferRef。

        参数：
        - lease：allocate 返回的 writing lease。
        - content：要写入 mmap 的字节。
        - media_type：媒体类型。
        - shape：raw 图像或 tensor 形状。
        - dtype：raw 数据类型。
        - layout：raw 数据布局。
        - pixel_format：像素格式。
        - readonly：返回引用是否只读。

        返回：
        - MmapBufferWriteResult：active lease 与 BufferRef。
        """

        self._ensure_open()
        if not isinstance(content, bytes) or not content:
            raise InvalidRequestError("mmap buffer 写入内容必须是非空 bytes")
        if len(content) > lease.size:
            raise InvalidRequestError(
                "mmap buffer 写入内容超过 lease 大小",
                details={"lease_id": lease.lease_id, "content_size": len(content), "lease_size": lease.size},
            )
        normalized_media_type = _require_stripped_text(media_type, "media_type")
        with self._lock:
            slot_index = self._require_current_slot_index(lease=lease, expected_states={"writing"})
            self._mmap.seek(lease.offset)
            self._mmap.write(content)
            if len(content) < lease.size:
                self._mmap.write(b"\x00" * (lease.size - len(content)))
            self._mmap.flush()
            active_lease = lease.model_copy(update={"state": "active", "size": len(content)})
            self._slots[slot_index].lease = active_lease
            buffer_ref = BufferRef(
                buffer_id=active_lease.buffer_id,
                lease_id=active_lease.lease_id,
                path=active_lease.file_path,
                offset=active_lease.offset,
                size=active_lease.size,
                shape=shape,
                dtype=_normalize_optional_text(dtype),
                layout=_normalize_optional_text(layout),
                pixel_format=_normalize_optional_text(pixel_format),
                media_type=normalized_media_type,
                readonly=readonly,
                broker_epoch=active_lease.broker_epoch,
                generation=active_lease.generation,
            )
            return MmapBufferWriteResult(lease=active_lease, buffer_ref=buffer_ref)

    def commit_lease(
        self,
        *,
        lease: BufferLease,
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        readonly: bool = True,
    ) -> MmapBufferWriteResult:
        """把已经由客户端 direct mmap 写完的 lease 发布为 active BufferRef。

        参数：
        - lease：allocate 返回的 writing lease。
        - media_type：媒体类型。
        - shape：raw 图像或 tensor 形状。
        - dtype：raw 数据类型。
        - layout：raw 数据布局。
        - pixel_format：像素格式。
        - readonly：返回引用是否只读。

        返回：
        - MmapBufferWriteResult：active lease 与 BufferRef。
        """

        self._ensure_open()
        normalized_media_type = _require_stripped_text(media_type, "media_type")
        with self._lock:
            slot_index = self._require_current_slot_index(lease=lease, expected_states={"writing"})
            self._mmap.flush()
            active_lease = lease.model_copy(update={"state": "active"})
            self._slots[slot_index].lease = active_lease
            buffer_ref = BufferRef(
                buffer_id=active_lease.buffer_id,
                lease_id=active_lease.lease_id,
                path=active_lease.file_path,
                offset=active_lease.offset,
                size=active_lease.size,
                shape=shape,
                dtype=_normalize_optional_text(dtype),
                layout=_normalize_optional_text(layout),
                pixel_format=_normalize_optional_text(pixel_format),
                media_type=normalized_media_type,
                readonly=readonly,
                broker_epoch=active_lease.broker_epoch,
                generation=active_lease.generation,
            )
            return MmapBufferWriteResult(lease=active_lease, buffer_ref=buffer_ref)

    def write_bytes(
        self,
        *,
        content: bytes,
        owner_kind: str,
        owner_id: str,
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> MmapBufferWriteResult:
        """分配槽位、写入字节并返回 BufferRef。

        参数：
        - content：要写入 mmap 的字节。
        - owner_kind：租约拥有者类型。
        - owner_id：租约拥有者实例 id。
        - media_type：媒体类型。
        - shape：raw 图像或 tensor 形状。
        - dtype：raw 数据类型。
        - layout：raw 数据布局。
        - pixel_format：像素格式。
        - ttl_seconds：可选过期秒数。
        - trace_id：链路追踪 id。

        返回：
        - MmapBufferWriteResult：active lease 与 BufferRef。
        """

        lease = self.allocate(
            size=len(content),
            owner_kind=owner_kind,
            owner_id=owner_id,
            ttl_seconds=ttl_seconds,
            trace_id=trace_id,
        )
        try:
            return self.write_lease(
                lease=lease,
                content=content,
                media_type=media_type,
                shape=shape,
                dtype=dtype,
                layout=layout,
                pixel_format=pixel_format,
            )
        except Exception:
            self.release(lease.lease_id)
            raise

    def create_frame_channel(self, *, stream_id: str, frame_capacity: int) -> dict[str, object]:
        """创建一个固定容量 ring buffer channel。

        参数：
        - stream_id：连续帧来源 id。
        - frame_capacity：该 channel 预留的帧槽位数量。

        返回：
        - dict[str, object]：channel 状态摘要。
        """

        self._ensure_open()
        normalized_stream_id = _require_stripped_text(stream_id, "stream_id")
        if frame_capacity <= 0:
            raise InvalidRequestError("ring buffer frame_capacity 必须大于 0")
        with self._lock:
            if normalized_stream_id in self._ring_channels:
                raise InvalidRequestError("ring buffer channel 已存在", details={"stream_id": normalized_stream_id})
            available_slots = [
                slot_index
                for slot_index, slot_state in enumerate(self._slots)
                if slot_state.lease is None and slot_state.frame is None
            ]
            if len(available_slots) < frame_capacity:
                raise InvalidRequestError(
                    "ring buffer 可用槽位不足",
                    details={
                        "stream_id": normalized_stream_id,
                        "frame_capacity": frame_capacity,
                        "available_slot_count": len(available_slots),
                    },
                )
            slot_indices = tuple(available_slots[:frame_capacity])
            for slot_index in slot_indices:
                self._slots[slot_index].frame = _FrameSlotState(
                    stream_id=normalized_stream_id,
                    sequence_id=-1,
                    buffer_id=self._build_frame_buffer_id(normalized_stream_id, slot_index),
                    offset=slot_index * self.config.slot_size_bytes,
                )
            channel = _RingChannelState(stream_id=normalized_stream_id, slot_indices=slot_indices)
            self._ring_channels[normalized_stream_id] = channel
            increment_safe_counter(self._frame_channel_count)
            self._max_used_count = max(self._max_used_count, self._count_used_slots_locked())
            return self._build_frame_channel_status_locked(channel)

    def allocate_frame(
        self,
        *,
        stream_id: str,
        size: int,
    ) -> dict[str, object]:
        """为 ring buffer 下一帧分配 writing 槽位。

        参数：
        - stream_id：连续帧来源 id。
        - size：当前帧有效字节数。

        返回：
        - dict[str, object]：客户端 direct mmap 写入所需的 reservation。
        """

        self._ensure_open()
        normalized_stream_id = _require_stripped_text(stream_id, "stream_id")
        _validate_size(size, self.config.slot_size_bytes)
        with self._lock:
            channel = self._require_frame_channel_locked(normalized_stream_id)
            slot_index = channel.slot_indices[channel.next_slot_position]
            slot_state = self._slots[slot_index]
            frame_state = slot_state.frame
            if frame_state is None or frame_state.stream_id != normalized_stream_id:
                raise InvalidRequestError("ring buffer 槽位不属于当前 stream", details={"stream_id": normalized_stream_id})
            if frame_state.state == "writing":
                raise InvalidRequestError("ring buffer 当前槽位仍处于 writing 状态", details={"stream_id": normalized_stream_id})
            if frame_state.state == "active":
                increment_safe_counter(channel.overwritten_frame_count)
                increment_safe_counter(self._frame_overwrite_count)
            slot_state.generation += 1
            sequence_id = channel.next_sequence_id
            channel.next_sequence_id += 1
            channel.next_slot_position = (channel.next_slot_position + 1) % len(channel.slot_indices)
            frame_state.sequence_id = sequence_id
            frame_state.size = size
            frame_state.generation = slot_state.generation
            frame_state.state = "writing"
            frame_state.media_type = None
            frame_state.shape = ()
            frame_state.dtype = None
            frame_state.layout = None
            frame_state.pixel_format = None
            frame_state.metadata = {}
            return {
                "pool_name": self.pool_name,
                "stream_id": normalized_stream_id,
                "sequence_id": sequence_id,
                "buffer_id": frame_state.buffer_id,
                "file_path": str(self.file_path),
                "offset": frame_state.offset,
                "size": size,
                "broker_epoch": self.broker_epoch,
                "generation": frame_state.generation,
            }

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
        """把已经 direct mmap 写完的 ring frame 发布为 FrameRef。

        参数：
        - reservation：allocate_frame 返回的写入 reservation。
        - media_type：当前帧媒体类型。
        - shape：raw 图像或 tensor 形状。
        - dtype：raw 数据类型。
        - layout：raw 数据布局。
        - pixel_format：像素格式。
        - metadata：附加元数据。

        返回：
        - FrameRef：可传给读取方的帧引用。
        """

        self._ensure_open()
        normalized_media_type = _require_stripped_text(media_type, "media_type")
        with self._lock:
            frame_state = self._require_writing_frame_for_reservation_locked(reservation)
            self._mmap.flush()
            frame_state.state = "active"
            frame_state.media_type = normalized_media_type
            frame_state.shape = tuple(shape)
            frame_state.dtype = _normalize_optional_text(dtype)
            frame_state.layout = _normalize_optional_text(layout)
            frame_state.pixel_format = _normalize_optional_text(pixel_format)
            frame_state.metadata = dict(metadata or {})
            channel = self._require_frame_channel_locked(frame_state.stream_id)
            increment_safe_counter(channel.published_frame_count)
            increment_safe_counter(self._frame_write_count)
            return self._build_frame_ref_locked(frame_state)

    def write_frame(
        self,
        *,
        stream_id: str,
        content: bytes,
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FrameRef:
        """写入一帧并返回 FrameRef。

        参数：
        - stream_id：连续帧来源 id。
        - content：当前帧字节内容。
        - media_type：当前帧媒体类型。
        - shape：raw 图像或 tensor 形状。
        - dtype：raw 数据类型。
        - layout：raw 数据布局。
        - pixel_format：像素格式。
        - metadata：附加元数据。

        返回：
        - FrameRef：当前帧引用。
        """

        if not isinstance(content, bytes) or not content:
            raise InvalidRequestError("ring buffer 写入内容必须是非空 bytes")
        reservation = self.allocate_frame(stream_id=stream_id, size=len(content))
        self._mmap.seek(int(reservation["offset"]))
        self._mmap.write(content)
        if len(content) < int(reservation["size"]):
            self._mmap.write(b"\x00" * (int(reservation["size"]) - len(content)))
        self._mmap.flush()
        return self.commit_frame(
            reservation=reservation,
            media_type=media_type,
            shape=shape,
            dtype=dtype,
            layout=layout,
            pixel_format=pixel_format,
            metadata=metadata,
        )

    def read_buffer_ref(self, buffer_ref: BufferRef) -> bytes:
        """读取 BufferRef 对应的字节，并校验 lease 一致性。

        参数：
        - buffer_ref：待读取的 BufferRef。

        返回：
        - bytes：引用范围内的字节内容。
        """

        self._ensure_open()
        with self._lock:
            lease = self._require_active_lease_for_ref(buffer_ref)
            self._mmap.seek(lease.offset)
            return self._mmap.read(buffer_ref.size)

    def validate_buffer_ref(self, buffer_ref: BufferRef) -> None:
        """校验 BufferRef 当前仍指向 active lease。

        参数：
        - buffer_ref：待读取的 BufferRef。
        """

        self._ensure_open()
        with self._lock:
            self._require_active_lease_for_ref(buffer_ref)

    def read_frame_ref(self, frame_ref: FrameRef) -> bytes:
        """读取 FrameRef 对应的帧字节。

        参数：
        - frame_ref：待读取的 FrameRef。

        返回：
        - bytes：引用范围内的帧字节内容。
        """

        self._ensure_open()
        with self._lock:
            frame_state = self._require_active_frame_for_ref(frame_ref)
            self._mmap.seek(frame_state.offset)
            return self._mmap.read(frame_ref.size)

    def validate_frame_ref(self, frame_ref: FrameRef) -> None:
        """校验 FrameRef 当前仍指向 active ring buffer 帧。

        参数：
        - frame_ref：待读取的 FrameRef。
        """

        self._ensure_open()
        with self._lock:
            self._require_active_frame_for_ref(frame_ref)

    def release(self, lease_id: str) -> None:
        """释放指定 lease 对应的槽位。

        参数：
        - lease_id：要释放的 lease id。
        """

        normalized_lease_id = _require_stripped_text(lease_id, "lease_id")
        with self._lock:
            for slot_state in self._slots:
                lease = slot_state.lease
                if lease is not None and lease.lease_id == normalized_lease_id:
                    slot_state.lease = None
                    increment_safe_counter(self._released_count)
                    return
        raise InvalidRequestError("mmap buffer lease 不存在", details={"lease_id": normalized_lease_id})

    def release_owner(
        self,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
        owner_id_prefix: str | None = None,
    ) -> int:
        """释放指定 owner 匹配的全部 lease。

        参数：
        - owner_kind：可选 owner 类型过滤条件。
        - owner_id：可选 owner id 精确匹配条件。
        - owner_id_prefix：可选 owner id 前缀匹配条件。

        返回：
        - int：本次释放的 lease 数量。
        """

        normalized_owner_kind = _normalize_optional_text(owner_kind)
        normalized_owner_id = _normalize_optional_text(owner_id)
        normalized_owner_id_prefix = _normalize_optional_text(owner_id_prefix)
        if normalized_owner_id is None and normalized_owner_id_prefix is None:
            raise InvalidRequestError("release_owner 必须提供 owner_id 或 owner_id_prefix")
        released_count = 0
        with self._lock:
            for slot_state in self._slots:
                lease = slot_state.lease
                if lease is None:
                    continue
                if normalized_owner_kind is not None and lease.owner_kind != normalized_owner_kind:
                    continue
                if normalized_owner_id is not None and lease.owner_id != normalized_owner_id:
                    continue
                if normalized_owner_id_prefix is not None and not lease.owner_id.startswith(
                    normalized_owner_id_prefix
                ):
                    continue
                slot_state.lease = None
                released_count += 1
            for _ in range(released_count):
                increment_safe_counter(self._released_count)
        return released_count

    def expire_leases(self, *, now: datetime | None = None) -> int:
        """回收已经过期的 active 或 writing lease。

        参数：
        - now：用于测试的当前时间；未提供时使用 UTC 当前时间。

        返回：
        - int：本次回收的 lease 数量。
        """

        current_time = now or datetime.now(timezone.utc)
        expired_count = 0
        with self._lock:
            for slot_state in self._slots:
                lease = slot_state.lease
                if lease is not None and lease.expires_at is not None and lease.expires_at <= current_time:
                    slot_state.lease = None
                    expired_count += 1
            for _ in range(expired_count):
                increment_safe_counter(self._expired_count)
        return expired_count

    def build_status(self) -> dict[str, object]:
        """构造当前 pool 的容量和运行计数。"""

        self._ensure_open()
        with self._lock:
            allocation_count_snapshot = snapshot_safe_counter(self._allocation_count)
            allocation_failure_count_snapshot = snapshot_safe_counter(self._allocation_failure_count)
            pool_full_count_snapshot = snapshot_safe_counter(self._pool_full_count)
            released_count_snapshot = snapshot_safe_counter(self._released_count)
            expired_count_snapshot = snapshot_safe_counter(self._expired_count)
            frame_channel_count_snapshot = snapshot_safe_counter(self._frame_channel_count)
            frame_write_count_snapshot = snapshot_safe_counter(self._frame_write_count)
            frame_overwrite_count_snapshot = snapshot_safe_counter(self._frame_overwrite_count)
            active_count = self._count_leases_by_state_locked("active")
            writing_count = self._count_leases_by_state_locked("writing")
            frame_active_count = self._count_frames_by_state_locked("active")
            frame_writing_count = self._count_frames_by_state_locked("writing")
            used_count = self._count_used_slots_locked()
            return {
                "pool_name": self.pool_name,
                "capacity_bytes": self.capacity_bytes,
                "slot_count": self.slot_count,
                "file_path": str(self.file_path),
                "active_count": active_count,
                "writing_count": writing_count,
                "frame_active_count": frame_active_count,
                "frame_writing_count": frame_writing_count,
                "frame_reserved_count": self._count_frame_slots_locked(),
                "used_count": used_count,
                "free_count": self.slot_count - used_count,
                "allocation_count": allocation_count_snapshot["value"],
                "allocation_count_rollover_count": allocation_count_snapshot["rollover_count"],
                "allocation_failure_count": allocation_failure_count_snapshot["value"],
                "allocation_failure_count_rollover_count": allocation_failure_count_snapshot["rollover_count"],
                "pool_full_count": pool_full_count_snapshot["value"],
                "pool_full_count_rollover_count": pool_full_count_snapshot["rollover_count"],
                "released_count": released_count_snapshot["value"],
                "released_count_rollover_count": released_count_snapshot["rollover_count"],
                "expired_count": expired_count_snapshot["value"],
                "expired_count_rollover_count": expired_count_snapshot["rollover_count"],
                "max_used_count": self._max_used_count,
                "frame_channel_count": frame_channel_count_snapshot["value"],
                "frame_channel_count_rollover_count": frame_channel_count_snapshot["rollover_count"],
                "frame_write_count": frame_write_count_snapshot["value"],
                "frame_write_count_rollover_count": frame_write_count_snapshot["rollover_count"],
                "frame_overwrite_count": frame_overwrite_count_snapshot["value"],
                "frame_overwrite_count_rollover_count": frame_overwrite_count_snapshot["rollover_count"],
                "frame_channels": [
                    self._build_frame_channel_status_locked(channel)
                    for channel in self._ring_channels.values()
                ],
            }

    def close(self) -> None:
        """关闭 mmap 和底层文件句柄。"""

        if self._closed:
            return
        self._mmap.close()
        self._file.close()
        self._closed = True

    def __enter__(self) -> MmapBufferPool:
        """进入 context manager 并返回当前 pool。"""

        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """退出 context manager 时关闭 pool。"""

        self.close()

    def _find_free_slot_index(self) -> int:
        """返回第一个可用槽位索引。"""

        for slot_index, slot_state in enumerate(self._slots):
            if slot_state.lease is None and slot_state.frame is None:
                return slot_index
        raise InvalidRequestError(
            "mmap buffer pool 已满",
            details={"pool_name": self.pool_name, "slot_count": self._slot_count},
        )

    def _count_used_slots_locked(self) -> int:
        """返回当前已占用槽位数量。"""

        return sum(1 for slot_state in self._slots if slot_state.lease is not None or slot_state.frame is not None)

    def _count_leases_by_state_locked(self, state: str) -> int:
        """按 lease 状态统计槽位数量。"""

        return sum(1 for slot_state in self._slots if slot_state.lease is not None and slot_state.lease.state == state)

    def _count_frames_by_state_locked(self, state: str) -> int:
        """按 frame 状态统计槽位数量。"""

        return sum(1 for slot_state in self._slots if slot_state.frame is not None and slot_state.frame.state == state)

    def _count_frame_slots_locked(self) -> int:
        """统计已经被 ring channel 预留的槽位数量。"""

        return sum(1 for slot_state in self._slots if slot_state.frame is not None)

    def _build_buffer_id(self, slot_index: int) -> str:
        """按槽位索引生成 buffer id。"""

        return f"{self.pool_name}:{slot_index}"

    def _build_frame_buffer_id(self, stream_id: str, slot_index: int) -> str:
        """按 stream 和槽位索引生成 frame buffer id。"""

        return f"{self.pool_name}:frame:{stream_id}:{slot_index}"

    def _build_frame_channel_status_locked(self, channel: _RingChannelState) -> dict[str, object]:
        """构造 ring channel 状态摘要。"""

        published_frame_count_snapshot = snapshot_safe_counter(channel.published_frame_count)
        overwritten_frame_count_snapshot = snapshot_safe_counter(channel.overwritten_frame_count)
        return {
            "stream_id": channel.stream_id,
            "frame_capacity": len(channel.slot_indices),
            "slot_indices": list(channel.slot_indices),
            "next_sequence_id": channel.next_sequence_id,
            "next_slot_position": channel.next_slot_position,
            "published_frame_count": published_frame_count_snapshot["value"],
            "published_frame_count_rollover_count": published_frame_count_snapshot["rollover_count"],
            "overwritten_frame_count": overwritten_frame_count_snapshot["value"],
            "overwritten_frame_count_rollover_count": overwritten_frame_count_snapshot["rollover_count"],
        }

    def _require_frame_channel_locked(self, stream_id: str) -> _RingChannelState:
        """读取指定 stream 的 ring channel。"""

        channel = self._ring_channels.get(stream_id)
        if channel is None:
            raise InvalidRequestError("ring buffer channel 不存在", details={"stream_id": stream_id})
        return channel

    def _require_writing_frame_for_reservation_locked(self, reservation: dict[str, object]) -> _FrameSlotState:
        """按写入 reservation 定位 writing frame 槽位。"""

        stream_id = _require_payload_str(reservation, "stream_id")
        buffer_id = _require_payload_str(reservation, "buffer_id")
        broker_epoch = _require_payload_str(reservation, "broker_epoch")
        sequence_id = _require_payload_int(reservation, "sequence_id")
        generation = _require_payload_int(reservation, "generation")
        if broker_epoch != self.broker_epoch:
            raise InvalidRequestError("ring buffer reservation 属于旧 broker epoch", details={"stream_id": stream_id})
        channel = self._require_frame_channel_locked(stream_id)
        for slot_index in channel.slot_indices:
            frame_state = self._slots[slot_index].frame
            if frame_state is None or frame_state.buffer_id != buffer_id:
                continue
            if frame_state.state != "writing":
                raise InvalidRequestError("ring buffer reservation 当前不可提交", details={"buffer_id": buffer_id})
            if frame_state.sequence_id != sequence_id or frame_state.generation != generation:
                raise InvalidRequestError("ring buffer reservation 已被复用", details={"buffer_id": buffer_id})
            return frame_state
        raise InvalidRequestError("ring buffer reservation 指向未知槽位", details={"buffer_id": buffer_id})

    def _build_frame_ref_locked(self, frame_state: _FrameSlotState) -> FrameRef:
        """按 active frame 状态构造 FrameRef。"""

        if frame_state.media_type is None:
            raise InvalidRequestError("ring buffer active frame 缺少 media_type")
        return FrameRef(
            stream_id=frame_state.stream_id,
            sequence_id=frame_state.sequence_id,
            buffer_id=frame_state.buffer_id,
            path=str(self.file_path),
            offset=frame_state.offset,
            size=frame_state.size,
            shape=frame_state.shape,
            dtype=frame_state.dtype,
            layout=frame_state.layout,
            pixel_format=frame_state.pixel_format,
            media_type=frame_state.media_type,
            broker_epoch=self.broker_epoch,
            generation=frame_state.generation,
            metadata=dict(frame_state.metadata),
        )

    def _require_current_slot_index(
        self,
        *,
        lease: BufferLease,
        expected_states: set[str],
    ) -> int:
        """校验 lease 仍指向当前槽位并返回槽位索引。"""

        if lease.broker_epoch != self.broker_epoch:
            raise InvalidRequestError("mmap buffer lease 属于旧 broker epoch", details={"lease_id": lease.lease_id})
        if lease.offset % self.config.slot_size_bytes != 0:
            raise InvalidRequestError("mmap buffer lease offset 未对齐槽位", details={"lease_id": lease.lease_id})
        slot_index = lease.offset // self.config.slot_size_bytes
        if slot_index < 0 or slot_index >= self._slot_count:
            raise InvalidRequestError("mmap buffer lease offset 超出 pool 范围", details={"lease_id": lease.lease_id})
        slot_state = self._slots[slot_index]
        current_lease = slot_state.lease
        if current_lease is None:
            raise InvalidRequestError("mmap buffer lease 已释放", details={"lease_id": lease.lease_id})
        if current_lease.lease_id != lease.lease_id or current_lease.generation != lease.generation:
            raise InvalidRequestError("mmap buffer lease 已被其他代次复用", details={"lease_id": lease.lease_id})
        if current_lease.state not in expected_states:
            raise InvalidRequestError(
                "mmap buffer lease 状态不允许当前操作",
                details={"lease_id": lease.lease_id, "state": current_lease.state},
            )
        return slot_index

    def _require_active_lease_for_ref(self, buffer_ref: BufferRef) -> BufferLease:
        """按 BufferRef 找到 active lease 并校验一致性。"""

        if buffer_ref.broker_epoch != self.broker_epoch:
            raise InvalidRequestError("BufferRef 属于旧 broker epoch", details={"lease_id": buffer_ref.lease_id})
        if Path(buffer_ref.path) != self.file_path:
            raise InvalidRequestError("BufferRef path 与当前 pool 不匹配", details={"path": buffer_ref.path})
        slot_index = buffer_ref.offset // self.config.slot_size_bytes
        if slot_index < 0 or slot_index >= self._slot_count:
            raise InvalidRequestError("BufferRef offset 超出 pool 范围", details={"lease_id": buffer_ref.lease_id})
        slot_state = self._slots[slot_index]
        lease = slot_state.lease
        if lease is None or lease.state != "active":
            raise InvalidRequestError("BufferRef 引用的 lease 当前不可读", details={"lease_id": buffer_ref.lease_id})
        if lease.buffer_id != buffer_ref.buffer_id or lease.offset != buffer_ref.offset:
            raise InvalidRequestError("BufferRef 与当前 lease 槽位不一致", details={"lease_id": buffer_ref.lease_id})
        if lease.lease_id != buffer_ref.lease_id or lease.generation != buffer_ref.generation:
            raise InvalidRequestError("BufferRef 引用的 lease 已被复用", details={"lease_id": buffer_ref.lease_id})
        if buffer_ref.size > lease.size:
            raise InvalidRequestError("BufferRef size 超过 lease size", details={"lease_id": buffer_ref.lease_id})
        return lease

    def _require_active_frame_for_ref(self, frame_ref: FrameRef) -> _FrameSlotState:
        """按 FrameRef 找到 active frame 并校验一致性。"""

        if frame_ref.broker_epoch != self.broker_epoch:
            raise InvalidRequestError("FrameRef 属于旧 broker epoch", details={"stream_id": frame_ref.stream_id})
        if Path(frame_ref.path) != self.file_path:
            raise InvalidRequestError("FrameRef path 与当前 pool 不匹配", details={"path": frame_ref.path})
        channel = self._require_frame_channel_locked(frame_ref.stream_id)
        for slot_index in channel.slot_indices:
            frame_state = self._slots[slot_index].frame
            if frame_state is None or frame_state.buffer_id != frame_ref.buffer_id:
                continue
            if frame_state.state != "active":
                raise InvalidRequestError("FrameRef 引用的帧当前不可读", details={"buffer_id": frame_ref.buffer_id})
            if frame_state.sequence_id != frame_ref.sequence_id or frame_state.generation != frame_ref.generation:
                raise InvalidRequestError("FrameRef 引用的帧已被覆盖或复用", details={"buffer_id": frame_ref.buffer_id})
            if frame_state.offset != frame_ref.offset:
                raise InvalidRequestError("FrameRef 与当前帧槽位不一致", details={"buffer_id": frame_ref.buffer_id})
            if frame_ref.size > frame_state.size:
                raise InvalidRequestError("FrameRef size 超过当前帧 size", details={"buffer_id": frame_ref.buffer_id})
            return frame_state
        raise InvalidRequestError("FrameRef 指向未知 ring buffer 槽位", details={"buffer_id": frame_ref.buffer_id})

    def _ensure_open(self) -> None:
        """确认 pool 尚未关闭。"""

        if self._closed:
            raise InvalidRequestError("mmap buffer pool 已关闭", details={"pool_name": self.pool_name})


def _validate_config(config: MmapBufferPoolConfig) -> MmapBufferPoolConfig:
    """校验 mmap pool 配置。"""

    _require_stripped_text(config.pool_name, "pool_name")
    _require_stripped_text(config.file_name, "file_name")
    if config.file_size_bytes <= 0:
        raise InvalidRequestError("mmap buffer pool file_size_bytes 必须大于 0")
    if config.slot_size_bytes <= 0:
        raise InvalidRequestError("mmap buffer pool slot_size_bytes 必须大于 0")
    if config.file_size_bytes % config.slot_size_bytes != 0:
        raise InvalidRequestError("mmap buffer pool file_size_bytes 必须是 slot_size_bytes 的整数倍")
    return config


def _validate_size(size: int, slot_size_bytes: int) -> None:
    """校验单次 lease 大小。"""

    if size <= 0:
        raise InvalidRequestError("mmap buffer lease size 必须大于 0")
    if size > slot_size_bytes:
        raise InvalidRequestError(
            "mmap buffer lease size 超过单槽容量",
            details={"size": size, "slot_size_bytes": slot_size_bytes},
        )


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空。"""

    normalized_value = value.strip()
    if not normalized_value:
        raise InvalidRequestError(f"{field_name} 不能为空")
    return normalized_value


def _normalize_optional_text(value: object) -> str | None:
    """规范化可选字符串字段。"""

    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _require_payload_str(payload: dict[str, object], field_name: str) -> str:
    """从内部 payload 中读取非空字符串字段。"""

    value = payload.get(field_name)
    normalized_value = value.strip() if isinstance(value, str) else ""
    if not normalized_value:
        raise InvalidRequestError("ring buffer payload 缺少必需字符串字段", details={"field_name": field_name})
    return normalized_value


def _require_payload_int(payload: dict[str, object], field_name: str) -> int:
    """从内部 payload 中读取整数字段。"""

    value = payload.get(field_name)
    if isinstance(value, bool):
        raise InvalidRequestError("ring buffer payload 字段必须是整数", details={"field_name": field_name})
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError("ring buffer payload 字段必须是整数", details={"field_name": field_name}) from exc