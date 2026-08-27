"""未接业务 composition root 的 LocalMessage EventRing v1 engine。"""

from __future__ import annotations

import mmap
import struct
from time import monotonic_ns, sleep
from typing import BinaryIO
from uuid import UUID, uuid4

from backend.contracts.ipc.local_message_profiles import EventRingChannelProfile
from backend.service.application.message_channels.errors import (
    ChannelClosedError,
    ChannelCorruptMessageError,
    ChannelRestartedError,
)
from backend.service.application.message_channels.models import (
    EventBatch,
    EventCursor,
    EventPublishResult,
)
from backend.service.infrastructure.ipc.local_message.common_layout import (
    CHANNEL_KIND_EVENT,
    COMMON_HEADER_SIZE,
    EVENT_FLAG_CLOSED,
    EVENT_HEADER,
    EVENT_SLOT_HEADER,
    EVENT_SLOT_HEADER_SIZE,
    FILE_FLAG_CLOSED,
    begin_owner_initialization,
    decode_profile_id,
    encode_profile_id,
    event_layout,
    finish_owner_initialization,
    pack_common_header,
    unpack_common_header,
)
from backend.service.infrastructure.ipc.local_message.guards import (
    acquire_owner,
    release_owner,
)
from backend.service.infrastructure.ipc.local_message.health import EventChannelHealth
from backend.service.infrastructure.ipc.local_message.paths import (
    LocalMessageChannelPaths,
)
from backend.service.infrastructure.ipc.mmap_primitives import (
    MmapOwnerLockBusyError,
    acquire_mmap_owner_lock,
    crc32_ieee,
    new_nonzero_u64_token,
    publish_u32,
    release_mmap_owner_lock,
)


_COMMON_FLAGS_OFFSET = 84
_EVENT_FLAGS_OFFSET = COMMON_HEADER_SIZE + 16
_EVENT_PUBLISHED_SEQUENCE_OFFSET = COMMON_HEADER_SIZE + 24
_EVENT_DROPPED_TOTAL_OFFSET = COMMON_HEADER_SIZE + 32


class MmapEventRingPublisher:
    """单 producer、覆盖式、非阻塞 EventRing publisher。"""

    def __init__(
        self,
        *,
        paths: LocalMessageChannelPaths,
        profile: EventRingChannelProfile,
        channel_id: UUID | None = None,
        session_id: UUID | None = None,
    ) -> None:
        """创建新 owner epoch/session 并清空旧 ring metadata。"""

        self.paths = paths
        self.profile = profile
        self.layout = event_layout(profile)
        self._requested_channel_id = channel_id
        self.channel_id = channel_id or UUID(int=0)
        self.session_id = session_id or uuid4()
        self.owner_epoch = new_nonzero_u64_token()
        self._owner_lock: BinaryIO | None = None
        self._file: BinaryIO | None = None
        self._view: mmap.mmap | None = None
        self._closed = False
        self._published_sequence = 0
        self._dropped_total = 0
        try:
            self._initialize_files()
        except Exception:
            self._close_handles()
            raise

    def try_publish(self, wire_bytes: bytes) -> EventPublishResult:
        """发布一条事件；正文过大时计入 drop 并立即返回 FULL。"""

        if self._closed:
            return EventPublishResult.CLOSED
        payload = bytes(wire_bytes)
        if len(payload) > self.profile.payload_capacity_bytes:
            self._dropped_total += 1
            struct.pack_into(
                "<Q", self._require_view(), _EVENT_DROPPED_TOTAL_OFFSET, self._dropped_total
            )
            return EventPublishResult.FULL
        sequence = self._published_sequence + 1
        slot_index = (sequence - 1) % self.profile.slot_count
        slot_offset = self._slot_offset(slot_index)
        current_generation = int(EVENT_SLOT_HEADER.unpack_from(self._require_view(), slot_offset)[0])
        writing_generation = current_generation + 1
        if writing_generation % 2 == 0:
            writing_generation += 1
        EVENT_SLOT_HEADER.pack_into(
            self._require_view(),
            slot_offset,
            writing_generation,
            sequence,
            len(payload),
            crc32_ieee(payload),
            self.owner_epoch,
            0,
        )
        payload_offset = slot_offset + EVENT_SLOT_HEADER_SIZE
        self._require_view()[payload_offset : payload_offset + len(payload)] = payload
        # even generation 是 slot publication；global sequence 最后发布。
        struct.pack_into("<Q", self._require_view(), slot_offset, writing_generation + 1)
        struct.pack_into(
            "<Q", self._require_view(), _EVENT_PUBLISHED_SEQUENCE_OFFSET, sequence
        )
        self._published_sequence = sequence
        return EventPublishResult.PUBLISHED

    def health(self) -> EventChannelHealth:
        """返回 producer 专属 health。"""

        return EventChannelHealth(
            channel_id=self.channel_id,
            owner_epoch=self.owner_epoch,
            session_id=self.session_id,
            closed=self._closed,
            published_sequence=self._published_sequence,
            dropped_total=self._dropped_total,
            reader_gap_total=0,
        )

    def close(self, *, deadline_ns: int) -> None:
        """幂等发布 graceful close；不等待或管理 reader 生命周期。"""

        del deadline_ns
        if self._closed:
            return
        self._closed = True
        view = self._view
        if view is not None:
            publish_u32(view, offset=_EVENT_FLAGS_OFFSET, value=EVENT_FLAG_CLOSED)
            publish_u32(view, offset=_COMMON_FLAGS_OFFSET, value=FILE_FLAG_CLOSED)
            view.flush()
        self._close_handles()

    def _initialize_files(self) -> None:
        """初始化 fixed mmap 与 Event profile header。"""

        self.paths.mmap_path.parent.mkdir(parents=True, exist_ok=True)
        self._owner_lock = acquire_owner(self.paths.owner_lock_path)
        existing_size = (
            self.paths.mmap_path.stat().st_size
            if self.paths.mmap_path.exists()
            else 0
        )
        if existing_size not in {0, self.layout.file_size_bytes}:
            raise ChannelCorruptMessageError("Event owner 文件长度与冻结 profile 不匹配")
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
                expected_kind=CHANNEL_KIND_EVENT,
                expected_fingerprint=self.layout.fingerprint,
            )
            if (
                self._requested_channel_id is not None
                and existing.channel_id != self._requested_channel_id
            ):
                raise ChannelCorruptMessageError("Event channel_id 与已有文件不匹配")
            self.channel_id = existing.channel_id
        else:
            self.channel_id = self._requested_channel_id or uuid4()
        packed_common = pack_common_header(
            channel_kind=CHANNEL_KIND_EVENT,
            fingerprint=self.layout.fingerprint,
            channel_id=self.channel_id,
            owner_epoch=self.owner_epoch,
        )
        begin_owner_initialization(view, packed_common)
        EVENT_HEADER.pack_into(
            view,
            COMMON_HEADER_SIZE,
            self.profile.slot_count,
            EVENT_SLOT_HEADER_SIZE,
            self.profile.payload_capacity_bytes,
            self.layout.slot_stride_bytes,
            0,
            0,
            0,
            0,
            int(self.profile.poll_interval_seconds * 1e9),
            int(self.profile.scan_interval_seconds * 1e9),
            self.session_id.bytes,
            self.layout.slot_region_offset,
            self.layout.file_size_bytes,
            encode_profile_id(self.profile.profile_id),
        )
        for slot_index in range(self.profile.slot_count):
            slot_offset = self._slot_offset(slot_index)
            view[slot_offset : slot_offset + EVENT_SLOT_HEADER_SIZE] = (
                b"\0" * EVENT_SLOT_HEADER_SIZE
            )
        finish_owner_initialization(view)
        view.flush()

    def _slot_offset(self, slot_index: int) -> int:
        """返回 slot header offset。"""

        return self.layout.slot_region_offset + slot_index * self.layout.slot_stride_bytes

    def _require_view(self) -> mmap.mmap:
        """返回活动 publisher view。"""

        if self._view is None:
            raise ChannelClosedError("Event publisher 已关闭")
        return self._view

    def _close_handles(self) -> None:
        """按 view、file、owner lock 顺序关闭。"""

        view, file, owner = self._view, self._file, self._owner_lock
        self._view = None
        self._file = None
        self._owner_lock = None
        if view is not None:
            view.close()
        if file is not None:
            file.close()
        if owner is not None:
            release_owner(owner)


class MmapEventRingReader:
    """按 owner epoch/session cursor 读取 EventRing。"""

    def __init__(
        self,
        *,
        paths: LocalMessageChannelPaths,
        profile: EventRingChannelProfile,
    ) -> None:
        """打开并严格验证 Event profile header。"""

        self.paths = paths
        self.profile = profile
        self.layout = event_layout(profile)
        self._file: BinaryIO | None = None
        self._view: mmap.mmap | None = None
        self._closed = False
        self._reader_gap_total = 0
        try:
            self._file = paths.mmap_path.open("r+b", buffering=0)
            if paths.mmap_path.stat().st_size != self.layout.file_size_bytes:
                raise ChannelCorruptMessageError("Event mmap 文件长度不匹配")
            self._view = mmap.mmap(
                self._file.fileno(), self.layout.file_size_bytes, access=mmap.ACCESS_READ
            )
            common = unpack_common_header(
                self._view,
                expected_kind=CHANNEL_KIND_EVENT,
                expected_fingerprint=self.layout.fingerprint,
            )
            self.channel_id = common.channel_id
            self.owner_epoch = common.owner_epoch
            values = self._validate_event_header()
            self.session_id = UUID(bytes=values[10])
        except FileNotFoundError as error:
            self._close_handles()
            raise ChannelClosedError("Event producer 文件不存在") from error
        except Exception:
            self._close_handles()
            raise

    def read(
        self,
        *,
        cursor: EventCursor | None,
        deadline_ns: int,
        limit: int,
    ) -> EventBatch:
        """等待事件或 close；检测覆盖 gap、torn slot 和 owner restart。"""

        if self._closed:
            raise ChannelClosedError("Event reader 已关闭")
        if limit <= 0:
            raise ValueError("Event read limit 必须大于 0")
        if cursor is not None and (
            cursor.owner_epoch != self.owner_epoch or cursor.session_id != self.session_id
        ):
            raise ChannelRestartedError("Event cursor 属于旧 owner epoch/session")
        while True:
            common = unpack_common_header(
                self._require_view(),
                expected_kind=CHANNEL_KIND_EVENT,
                expected_fingerprint=self.layout.fingerprint,
            )
            if common.owner_epoch != self.owner_epoch:
                raise ChannelRestartedError("Event producer owner epoch 已变化")
            header = EVENT_HEADER.unpack_from(self._require_view(), COMMON_HEADER_SIZE)
            if UUID(bytes=header[10]) != self.session_id:
                raise ChannelRestartedError("Event producer session 已变化")
            published_sequence = int(header[6])
            producer_closed = bool(int(header[4]) & EVENT_FLAG_CLOSED)
            batch = self._read_available(
                cursor=cursor,
                published_sequence=published_sequence,
                producer_closed=producer_closed,
                limit=limit,
            )
            if batch.events or batch.gap_detected or producer_closed:
                return batch
            now_ns = monotonic_ns()
            if now_ns >= deadline_ns:
                return batch
            sleep(min(self.profile.poll_interval_seconds, (deadline_ns - now_ns) / 1e9))

    def owner_alive(self) -> bool:
        """使用 owner guard 判断异常退出；PID 不是权威依据。"""

        try:
            handle = acquire_mmap_owner_lock(self.paths.owner_lock_path)
        except MmapOwnerLockBusyError:
            return True
        release_mmap_owner_lock(handle)
        return False

    def health(self) -> EventChannelHealth:
        """返回 reader 观察到的 Event 专属 health。"""

        header = EVENT_HEADER.unpack_from(self._require_view(), COMMON_HEADER_SIZE)
        return EventChannelHealth(
            channel_id=self.channel_id,
            owner_epoch=self.owner_epoch,
            session_id=self.session_id,
            closed=bool(int(header[4]) & EVENT_FLAG_CLOSED),
            published_sequence=int(header[6]),
            dropped_total=int(header[7]),
            reader_gap_total=self._reader_gap_total,
        )

    def close(self, *, deadline_ns: int) -> None:
        """幂等关闭 reader view。"""

        del deadline_ns
        if self._closed:
            return
        self._closed = True
        self._close_handles()

    def _read_available(
        self,
        *,
        cursor: EventCursor | None,
        published_sequence: int,
        producer_closed: bool,
        limit: int,
    ) -> EventBatch:
        """从当前 ring 快照读取稳定 slots。"""

        previous_sequence = cursor.sequence if cursor is not None else 0
        oldest_sequence = max(1, published_sequence - self.profile.slot_count + 1)
        start_sequence = max(previous_sequence + 1, oldest_sequence)
        gap_detected = previous_sequence > 0 and previous_sequence < oldest_sequence - 1
        if published_sequence >= start_sequence and published_sequence - start_sequence + 1 > limit:
            start_sequence = published_sequence - limit + 1
            gap_detected = True
        events: list[bytes] = []
        for sequence in range(start_sequence, published_sequence + 1):
            payload = self._read_slot(sequence)
            if payload is None:
                gap_detected = True
                continue
            events.append(payload)
        if gap_detected:
            self._reader_gap_total += 1
        return EventBatch(
            events=tuple(events),
            next_cursor=EventCursor(
                owner_epoch=self.owner_epoch,
                session_id=self.session_id,
                sequence=published_sequence,
            ),
            gap_detected=gap_detected,
            producer_closed=producer_closed,
        )

    def _read_slot(self, expected_sequence: int) -> bytes | None:
        """双读 even generation 并校验 sequence、epoch、size 和 CRC。"""

        slot_index = (expected_sequence - 1) % self.profile.slot_count
        slot_offset = self._slot_offset(slot_index)
        first = EVENT_SLOT_HEADER.unpack_from(self._require_view(), slot_offset)
        generation, sequence, payload_size, payload_crc, owner_epoch, _flags = first
        if generation % 2 != 0 or sequence != expected_sequence:
            return None
        if owner_epoch != self.owner_epoch:
            return None
        if not 0 <= payload_size <= self.profile.payload_capacity_bytes:
            return None
        payload_offset = slot_offset + EVENT_SLOT_HEADER_SIZE
        payload = bytes(
            self._require_view()[payload_offset : payload_offset + payload_size]
        )
        second = EVENT_SLOT_HEADER.unpack_from(self._require_view(), slot_offset)
        if first != second or crc32_ieee(payload) != payload_crc:
            return None
        return payload

    def _validate_event_header(self) -> tuple[object, ...]:
        """逐字段验证 Event profile header。"""

        values = EVENT_HEADER.unpack_from(self._require_view(), COMMON_HEADER_SIZE)
        expected = (
            self.profile.slot_count,
            EVENT_SLOT_HEADER_SIZE,
            self.profile.payload_capacity_bytes,
            self.layout.slot_stride_bytes,
        )
        if values[:4] != expected:
            raise ChannelCorruptMessageError("Event profile header 不匹配")
        if int(values[8]) != int(self.profile.poll_interval_seconds * 1e9):
            raise ChannelCorruptMessageError("Event poll profile 不匹配")
        if int(values[9]) != int(self.profile.scan_interval_seconds * 1e9):
            raise ChannelCorruptMessageError("Event scan profile 不匹配")
        if int(values[11]) != self.layout.slot_region_offset or int(values[12]) != self.layout.file_size_bytes:
            raise ChannelCorruptMessageError("Event layout offset/size 不匹配")
        if decode_profile_id(values[13]) != self.profile.profile_id:
            raise ChannelCorruptMessageError("Event profile_id 不匹配")
        return values

    def _slot_offset(self, slot_index: int) -> int:
        """返回 slot header offset。"""

        return self.layout.slot_region_offset + slot_index * self.layout.slot_stride_bytes

    def _require_view(self) -> mmap.mmap:
        """返回活动 reader view。"""

        if self._view is None:
            raise ChannelClosedError("Event reader 已关闭")
        return self._view

    def _close_handles(self) -> None:
        """幂等关闭 reader mapping。"""

        view, file = self._view, self._file
        self._view = None
        self._file = None
        if view is not None:
            view.close()
        if file is not None:
            file.close()
