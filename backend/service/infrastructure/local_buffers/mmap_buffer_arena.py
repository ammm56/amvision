"""LocalBuffer 固定 arena、持久 descriptor 与 guard 生命周期实现。"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import mmap
import os
from pathlib import Path
from secrets import token_bytes
import struct
import sys
from threading import Condition, RLock
from time import monotonic, monotonic_ns
from typing import BinaryIO, Iterator, Literal
from uuid import uuid4

from backend.service.infrastructure.ipc.mmap_primitives import (
    acquire_mmap_owner_lock,
    open_mmap_guard_identity,
    release_mmap_owner_lock,
    try_lock_byte_range_file,
    unlock_byte_range_file,
)
from backend.service.infrastructure.local_buffers.buddy_allocator import (
    BuddyAllocationError,
    BuddyArenaAllocator,
    BuddyArenaGeometry,
    BuddyExtent,
)


_MAGIC = b"AMVLBA01"
_LAYOUT_VERSION = 1
_HEADER_SIZE = 256
_DESCRIPTOR_STRIDE = 256
_HEADER = struct.Struct("<8sIIIIIIQQQQ16s32sQ")
_DESCRIPTOR = struct.Struct("<IIQ16s16sQQQQQIIQ")

_STATE_FREE = 0
_STATE_WRITING = 1
_STATE_ACTIVE = 2
_STATE_FRAME_RESERVED = 3
_STATE_REVOKING = 4
_STATE_QUARANTINED = 5

_DOMAIN_GENERAL = 0
_DOMAIN_HUGE_RESERVE = 1

ArenaLeaseState = Literal[
    "free",
    "writing",
    "active",
    "frame_reserved",
    "revoking",
    "quarantined",
]


class LocalBufferArenaError(RuntimeError):
    """表示固定 arena layout、identity 或生命周期错误。"""


class LocalBufferArenaIntegrityError(LocalBufferArenaError):
    """表示 arena 容量守恒或 allocator identity 已不可信。"""


class LocalBufferArenaCloseBusyError(LocalBufferArenaError):
    """表示仍有当前进程借用的 mmap view，arena 暂时不能关闭。"""


@dataclass(frozen=True, slots=True)
class MmapBufferArenaConfig:
    """描述单个 Broker owner 的固定 LocalBuffer arena。"""

    root_dir: Path
    arena_id: str
    arena_size_bytes: int
    min_block_size_bytes: int
    max_allocation_bytes: int
    huge_reserve_bytes: int = 0
    reader_guard_slots: int = 64
    flush_on_write: bool = False
    revocation_grace_seconds: float = 5.0

    def __post_init__(self) -> None:
        """校验路径无关配置并冻结 buddy geometry。"""

        if struct.calcsize("P") != 8 or sys.maxsize <= 2**32:
            raise LocalBufferArenaError("LocalBuffer 正式数据面只支持 64-bit 进程")
        if not self.arena_id.strip():
            raise ValueError("arena_id 不能为空")
        if self.reader_guard_slots <= 0:
            raise ValueError("reader_guard_slots 必须大于 0")
        if self.revocation_grace_seconds <= 0:
            raise ValueError("revocation_grace_seconds 必须大于 0")
        BuddyArenaGeometry(
            arena_size_bytes=self.arena_size_bytes,
            min_block_size_bytes=self.min_block_size_bytes,
            max_allocation_bytes=self.max_allocation_bytes,
            huge_reserve_bytes=self.huge_reserve_bytes,
        )

    @property
    def geometry(self) -> BuddyArenaGeometry:
        """返回经过相同规则校验的 buddy geometry。"""

        return BuddyArenaGeometry(
            arena_size_bytes=self.arena_size_bytes,
            min_block_size_bytes=self.min_block_size_bytes,
            max_allocation_bytes=self.max_allocation_bytes,
            huge_reserve_bytes=self.huge_reserve_bytes,
        )


@dataclass(frozen=True, slots=True)
class ArenaLeaseReceipt:
    """保存服务端执行 transfer/release 所需的完整私有 identity。"""

    arena_id: str
    descriptor_index: int
    descriptor_generation: int
    broker_epoch: str
    lease_token: bytes
    owner_token: bytes
    deadline_ns: int
    offset: int
    allocation_capacity_bytes: int
    content_length: int


@dataclass(frozen=True, slots=True)
class ArenaDescriptorSnapshot:
    """描述一个持久 descriptor 的已发布状态。"""

    descriptor_index: int
    state: ArenaLeaseState
    descriptor_generation: int
    lease_token: bytes
    owner_token: bytes
    offset: int
    allocation_capacity_bytes: int
    content_length: int
    deadline_ns: int
    revocation_deadline_ns: int
    order: int
    domain: Literal["general", "huge_reserve"]
    publication_generation: int


class MmapBufferArena:
    """管理固定大小 arena、持久 descriptor 和跨进程 guard。"""

    def __init__(self, config: MmapBufferArenaConfig) -> None:
        """打开或创建严格匹配 layout 的 arena，并恢复旧 lease。"""

        self.config = config
        self.geometry = config.geometry
        self._allocator = BuddyArenaAllocator(self.geometry)
        self._allocator_lock = RLock()
        self._publication_lock = RLock()
        self._lifecycle = Condition(RLock())
        self._lifecycle_state: Literal[
            "open", "closing", "close_blocked", "closed"
        ] = "open"
        self._active_borrows = 0
        self._close_blocked_count = 0
        self._allocation_disabled = False
        self._closed = False
        self._publication_generation = 0
        self._broker_epoch_bytes = uuid4().bytes
        self.broker_epoch = self._broker_epoch_bytes.hex()
        self.layout_fingerprint = _build_layout_fingerprint(config)

        local_buffer_dir = config.root_dir.resolve() / "local-buffer"
        local_buffer_dir.mkdir(parents=True, exist_ok=True)
        self.arena_path = local_buffer_dir / "images.mmap"
        self.allocator_path = local_buffer_dir / "state.mmap"
        self.guard_path = local_buffer_dir / "access.guard"
        self.owner_lock_path = local_buffer_dir / "owner.lock"
        self._owner_lock = acquire_mmap_owner_lock(self.owner_lock_path)
        self._arena_file: BinaryIO | None = None
        self._allocator_file: BinaryIO | None = None
        self._arena_mmap: mmap.mmap | None = None
        self._allocator_mmap: mmap.mmap | None = None
        self._guard_file: BinaryIO | None = None
        try:
            self._open_files()
            existing = self._initialize_or_validate_metadata()
            self._initialize_guard_file(existing=existing)
            if existing:
                self._restore_descriptors()
            self._write_header()
            if existing:
                self._recover_previous_epoch()
        except BaseException:
            self.close()
            raise

    @property
    def descriptor_count(self) -> int:
        """返回固定 descriptor 数量。"""

        return self.geometry.descriptor_count

    def allocate(
        self,
        *,
        content_length: int,
        deadline_ns: int,
        frame_reserved: bool = False,
    ) -> ArenaLeaseReceipt:
        """分配最小连续 extent 并最后发布 WRITING/FRAME_RESERVED。"""

        self._ensure_open()
        if deadline_ns <= monotonic_ns():
            raise ValueError("deadline_ns 必须位于未来")
        if self._allocation_disabled:
            raise LocalBufferArenaIntegrityError(
                "LocalBuffer arena 完整性已降级，拒绝新的 allocation"
            )
        with self._allocator_lock:
            descriptor_index = self._find_free_descriptor_locked()
            try:
                extent = self._allocator.allocate(
                    content_length,
                    allow_huge_reserve=not frame_reserved,
                )
            except BuddyAllocationError as error:
                if error.kind == "integrity":
                    self._allocation_disabled = True
                raise
            try:
                current = self._read_descriptor(descriptor_index)
                generation = current.descriptor_generation or 1
                lease_token = token_bytes(16)
                owner_token = token_bytes(16)
                state = "frame_reserved" if frame_reserved else "writing"
                self._publish_descriptor(
                    descriptor_index=descriptor_index,
                    state=state,
                    descriptor_generation=generation,
                    lease_token=lease_token,
                    owner_token=owner_token,
                    extent=extent,
                    deadline_ns=deadline_ns,
                    revocation_deadline_ns=0,
                )
            except Exception:
                self._allocator.free(extent)
                raise
        return ArenaLeaseReceipt(
            arena_id=self.config.arena_id,
            descriptor_index=descriptor_index,
            descriptor_generation=generation,
            broker_epoch=self.broker_epoch,
            lease_token=lease_token,
            owner_token=owner_token,
            deadline_ns=deadline_ns,
            offset=extent.offset,
            allocation_capacity_bytes=extent.capacity_bytes,
            content_length=content_length,
        )

    def publish_active(self, receipt: ArenaLeaseReceipt) -> ArenaLeaseReceipt:
        """校验 WRITING identity 并最后发布 ACTIVE。"""

        with self._publication_guard(receipt.descriptor_index):
            descriptor = self._require_receipt(receipt, expected_states={"writing"})
            if monotonic_ns() >= descriptor.deadline_ns:
                raise LocalBufferArenaError("LocalBuffer writing lease 已超过 deadline")
            self._write_descriptor_state(
                descriptor_index=receipt.descriptor_index,
                state="active",
            )
        return receipt

    def resize_writing_content(
        self,
        receipt: ArenaLeaseReceipt,
        *,
        content_length: int,
    ) -> ArenaLeaseReceipt:
        """发布 ACTIVE 前把预留 extent 收敛为实际有效长度。"""

        if content_length <= 0 or content_length > receipt.allocation_capacity_bytes:
            raise ValueError("content_length 超出预分配 extent")
        with self._allocator_lock:
            with self._publication_guard(receipt.descriptor_index):
                descriptor = self._require_receipt(
                    receipt,
                    expected_states={"writing"},
                )
                current_extent = _descriptor_extent(descriptor)
                resized_extent = self._allocator.resize_content_length(
                    current_extent,
                    content_length=content_length,
                )
                try:
                    self._publish_descriptor(
                        descriptor_index=descriptor.descriptor_index,
                        state="writing",
                        descriptor_generation=descriptor.descriptor_generation,
                        lease_token=descriptor.lease_token,
                        owner_token=descriptor.owner_token,
                        extent=resized_extent,
                        deadline_ns=descriptor.deadline_ns,
                        revocation_deadline_ns=descriptor.revocation_deadline_ns,
                        publication_guard_held=True,
                    )
                except Exception:
                    self._allocator.resize_content_length(
                        resized_extent,
                        content_length=current_extent.content_length,
                    )
                    raise
        return ArenaLeaseReceipt(
            arena_id=receipt.arena_id,
            descriptor_index=receipt.descriptor_index,
            descriptor_generation=receipt.descriptor_generation,
            broker_epoch=receipt.broker_epoch,
            lease_token=receipt.lease_token,
            owner_token=receipt.owner_token,
            deadline_ns=receipt.deadline_ns,
            offset=receipt.offset,
            allocation_capacity_bytes=receipt.allocation_capacity_bytes,
            content_length=content_length,
        )

    def transfer_owner(
        self,
        receipt: ArenaLeaseReceipt,
        *,
        new_deadline_ns: int,
    ) -> ArenaLeaseReceipt:
        """CAS 更新 owner token 与 deadline，不改变公开 locator。"""

        if new_deadline_ns <= monotonic_ns():
            raise ValueError("new_deadline_ns 必须位于未来")
        new_owner_token = token_bytes(16)
        with self._publication_guard(receipt.descriptor_index):
            descriptor = self._require_receipt(
                receipt,
                expected_states={"writing", "active", "frame_reserved"},
            )
            updated = ArenaLeaseReceipt(
                arena_id=receipt.arena_id,
                descriptor_index=receipt.descriptor_index,
                descriptor_generation=receipt.descriptor_generation,
                broker_epoch=receipt.broker_epoch,
                lease_token=receipt.lease_token,
                owner_token=new_owner_token,
                deadline_ns=new_deadline_ns,
                offset=receipt.offset,
                allocation_capacity_bytes=receipt.allocation_capacity_bytes,
                content_length=receipt.content_length,
            )
            self._publish_descriptor(
                descriptor_index=receipt.descriptor_index,
                state=descriptor.state,
                descriptor_generation=descriptor.descriptor_generation,
                lease_token=descriptor.lease_token,
                owner_token=new_owner_token,
                extent=_descriptor_extent(descriptor),
                deadline_ns=new_deadline_ns,
                revocation_deadline_ns=descriptor.revocation_deadline_ns,
                publication_guard_held=True,
            )
            return updated

    def publish_external_active_and_transfer(
        self,
        receipt: ArenaLeaseReceipt,
        *,
        new_deadline_ns: int,
    ) -> ArenaLeaseReceipt:
        """在 external writer 已退出后原子发布 ACTIVE 并更新 owner。

        SDK 必须先释放 writer guard，再发布 mailbox REQUEST。REQUEST 已可见时
        writer guard 仍被占用属于协议错误；这里使用非阻塞 guard，避免 Broker
        线程进入隐藏等待或把仍可写的图片暴露给 Runtime。
        """

        if new_deadline_ns <= monotonic_ns():
            raise ValueError("new_deadline_ns 必须位于未来")
        new_owner_token = token_bytes(16)
        try:
            with self.hold_writer_guard(receipt.descriptor_index):
                with self._publication_guard(receipt.descriptor_index):
                    descriptor = self._require_receipt(
                        receipt,
                        expected_states={"writing"},
                    )
                    if monotonic_ns() >= descriptor.deadline_ns:
                        raise LocalBufferArenaError(
                            "LocalBuffer writing lease 已超过 deadline"
                        )
                    updated = ArenaLeaseReceipt(
                        arena_id=receipt.arena_id,
                        descriptor_index=receipt.descriptor_index,
                        descriptor_generation=receipt.descriptor_generation,
                        broker_epoch=receipt.broker_epoch,
                        lease_token=receipt.lease_token,
                        owner_token=new_owner_token,
                        deadline_ns=new_deadline_ns,
                        offset=receipt.offset,
                        allocation_capacity_bytes=receipt.allocation_capacity_bytes,
                        content_length=receipt.content_length,
                    )
                    self._publish_descriptor(
                        descriptor_index=descriptor.descriptor_index,
                        state="active",
                        descriptor_generation=descriptor.descriptor_generation,
                        lease_token=descriptor.lease_token,
                        owner_token=new_owner_token,
                        extent=_descriptor_extent(descriptor),
                        deadline_ns=new_deadline_ns,
                        revocation_deadline_ns=descriptor.revocation_deadline_ns,
                        publication_guard_held=True,
                    )
                    return updated
        except (BlockingIOError, OSError) as error:
            raise LocalBufferArenaError(
                "external LocalBuffer writer guard 仍被占用"
            ) from error

    def transfer_owners_batch(
        self,
        receipts: tuple[ArenaLeaseReceipt, ...],
        *,
        new_deadline_ns: int,
    ) -> tuple[ArenaLeaseReceipt, ...]:
        """全量校验后一次性更新一组 owner token 和 deadline。"""

        if new_deadline_ns <= monotonic_ns():
            raise ValueError("new_deadline_ns 必须位于未来")
        if not receipts:
            return ()
        identities = {
            (item.descriptor_index, item.descriptor_generation, item.lease_token)
            for item in receipts
        }
        if len(identities) != len(receipts):
            raise LocalBufferArenaError("batch handoff 包含重复 lease identity")
        ordered_indices = sorted(item.descriptor_index for item in receipts)
        if len(ordered_indices) != len(set(ordered_indices)):
            raise LocalBufferArenaError("batch handoff descriptor 重复")
        with ExitStack() as stack:
            for descriptor_index in ordered_indices:
                stack.enter_context(self._publication_guard(descriptor_index))
            descriptors = [
                self._require_receipt(
                    receipt,
                    expected_states={"writing", "active", "frame_reserved"},
                )
                for receipt in receipts
            ]
            new_owner_tokens = [token_bytes(16) for _item in receipts]
            updated: list[ArenaLeaseReceipt] = []
            try:
                for receipt, descriptor, owner_token in zip(
                    receipts,
                    descriptors,
                    new_owner_tokens,
                    strict=True,
                ):
                    self._publish_descriptor(
                        descriptor_index=descriptor.descriptor_index,
                        state=descriptor.state,
                        descriptor_generation=descriptor.descriptor_generation,
                        lease_token=descriptor.lease_token,
                        owner_token=owner_token,
                        extent=_descriptor_extent(descriptor),
                        deadline_ns=new_deadline_ns,
                        revocation_deadline_ns=descriptor.revocation_deadline_ns,
                        publication_guard_held=True,
                    )
                    updated.append(
                        ArenaLeaseReceipt(
                            arena_id=receipt.arena_id,
                            descriptor_index=receipt.descriptor_index,
                            descriptor_generation=receipt.descriptor_generation,
                            broker_epoch=receipt.broker_epoch,
                            lease_token=receipt.lease_token,
                            owner_token=owner_token,
                            deadline_ns=new_deadline_ns,
                            offset=receipt.offset,
                            allocation_capacity_bytes=(
                                receipt.allocation_capacity_bytes
                            ),
                            content_length=receipt.content_length,
                        )
                    )
            except Exception as error:
                rollback_failed = self._rollback_batch_descriptors(descriptors)
                if rollback_failed:
                    raise LocalBufferArenaIntegrityError(
                        "batch handoff 写入失败且部分 descriptor 无法回滚，"
                        "相关 lease 已进入 REVOKING"
                    ) from error
                raise LocalBufferArenaError(
                    "batch handoff 写入失败，已回滚全部 descriptor"
                ) from error
            return tuple(updated)

    def _rollback_batch_descriptors(
        self,
        descriptors: list[ArenaDescriptorSnapshot],
    ) -> bool:
        """在 publication guards 已持有时逆序恢复批量更新前快照。"""

        rollback_failed = False
        for descriptor in reversed(descriptors):
            try:
                self._publish_descriptor(
                    descriptor_index=descriptor.descriptor_index,
                    state=descriptor.state,
                    descriptor_generation=descriptor.descriptor_generation,
                    lease_token=descriptor.lease_token,
                    owner_token=descriptor.owner_token,
                    extent=_descriptor_extent(descriptor),
                    deadline_ns=descriptor.deadline_ns,
                    revocation_deadline_ns=descriptor.revocation_deadline_ns,
                    publication_guard_held=True,
                )
            except Exception:
                rollback_failed = True
                try:
                    current = self._read_descriptor(descriptor.descriptor_index)
                    self._publish_descriptor(
                        descriptor_index=current.descriptor_index,
                        state="revoking",
                        descriptor_generation=current.descriptor_generation,
                        lease_token=current.lease_token,
                        owner_token=current.owner_token,
                        extent=_descriptor_extent(current),
                        deadline_ns=current.deadline_ns,
                        revocation_deadline_ns=(
                            monotonic_ns()
                            + int(self.config.revocation_grace_seconds * 1_000_000_000)
                        ),
                        publication_guard_held=True,
                    )
                except Exception:
                    self._allocation_disabled = True
        return rollback_failed

    def allocate_frame_channel(
        self,
        *,
        frame_count: int,
        max_frame_content_length: int,
        deadline_ns: int,
    ) -> tuple[ArenaLeaseReceipt, ...]:
        """在单个 allocator 临界区内全有或全无地预留 frame extents。"""

        if frame_count <= 0:
            raise ValueError("frame_count 必须大于 0")
        allocated: list[ArenaLeaseReceipt] = []
        with self._allocator_lock:
            try:
                for _frame_index in range(frame_count):
                    allocated.append(
                        self.allocate(
                            content_length=max_frame_content_length,
                            deadline_ns=deadline_ns,
                            frame_reserved=True,
                        )
                    )
            except Exception:
                for receipt in reversed(allocated):
                    result = self.request_reclaim(receipt)
                    if result != "released":
                        raise LocalBufferArenaError(
                            "frame channel rollback 未能立即释放未发布 extent"
                        )
                raise
        return tuple(allocated)

    def destroy_frame_channel(
        self,
        receipts: tuple[ArenaLeaseReceipt, ...],
    ) -> tuple[str, ...]:
        """撤销 channel 全部 extent；reader 未释放的项保持 REVOKING。"""

        return tuple(self.request_reclaim(item) for item in receipts)

    def validate_receipt(
        self,
        receipt: ArenaLeaseReceipt,
        *,
        expected_states: set[ArenaLeaseState],
    ) -> ArenaDescriptorSnapshot:
        """在 publication guard 内重新校验完整 receipt。"""

        with self._publication_guard(receipt.descriptor_index):
            return self._require_receipt(receipt, expected_states=expected_states)

    def request_reclaim(
        self,
        receipt: ArenaLeaseReceipt,
        *,
        now_ns: int | None = None,
    ) -> str:
        """发布 REVOKING 后持续持有全部外部 guard，再 FREE/merge。"""

        current_ns = monotonic_ns() if now_ns is None else now_ns
        try:
            with self._publication_guard(receipt.descriptor_index):
                descriptor = self._require_receipt(
                    receipt,
                    expected_states={
                        "writing",
                        "active",
                        "frame_reserved",
                        "revoking",
                        "quarantined",
                    },
                )
                if descriptor.state not in {"revoking", "quarantined"}:
                    revocation_deadline = current_ns + int(
                        self.config.revocation_grace_seconds * 1_000_000_000
                    )
                    self._publish_descriptor(
                        descriptor_index=receipt.descriptor_index,
                        state="revoking",
                        descriptor_generation=descriptor.descriptor_generation,
                        lease_token=descriptor.lease_token,
                        owner_token=descriptor.owner_token,
                        extent=_descriptor_extent(descriptor),
                        deadline_ns=descriptor.deadline_ns,
                        revocation_deadline_ns=revocation_deadline,
                        publication_guard_held=True,
                    )
        except LocalBufferArenaError:
            return "stale"
        return self._try_finalize_reclaim(receipt, current_ns=current_ns)

    def sweep(self, *, now_ns: int | None = None) -> dict[str, int]:
        """推进到期、REVOKING 和 QUARANTINED descriptor。"""

        current_ns = monotonic_ns() if now_ns is None else now_ns
        released = 0
        quarantined = 0
        for descriptor_index in range(self.descriptor_count):
            descriptor = self._read_descriptor(descriptor_index)
            if descriptor.state == "free":
                continue
            if descriptor.state not in {"revoking", "quarantined"}:
                if descriptor.deadline_ns > current_ns:
                    continue
            receipt = self._receipt_from_descriptor(descriptor)
            result = self.request_reclaim(receipt, now_ns=current_ns)
            released += int(result == "released")
            quarantined += int(result == "quarantined")
        return {"released_count": released, "quarantined_count": quarantined}

    def descriptor_snapshot(self, descriptor_index: int) -> ArenaDescriptorSnapshot:
        """返回已发布 descriptor 快照。"""

        with self._publication_guard(descriptor_index):
            return self._read_descriptor(descriptor_index)

    def build_status(self) -> dict[str, object]:
        """构造直接满足 general/reserve 守恒式的容量状态。"""

        with self._lifecycle:
            lifecycle_state = self._lifecycle_state
            active_borrow_count = self._active_borrows
            close_blocked_count = self._close_blocked_count
        allocator_status = self._allocator.snapshot()
        buckets = {
            domain: {
                "reserved_writing": 0,
                "active": 0,
                "frame_reserved": 0,
                "revoking": 0,
                "quarantined": 0,
            }
            for domain in ("general", "huge_reserve")
        }
        published_content = 0
        rounding_waste = 0
        for descriptor_index in range(self.descriptor_count):
            item = self._read_descriptor(descriptor_index)
            if item.state == "free":
                continue
            bucket_name = {
                "writing": "reserved_writing",
                "active": "active",
                "frame_reserved": "frame_reserved",
                "revoking": "revoking",
                "quarantined": "quarantined",
            }[item.state]
            buckets[item.domain][bucket_name] += item.allocation_capacity_bytes
            if item.state in {"writing", "active", "frame_reserved"}:
                published_content += item.content_length
                if item.state != "frame_reserved":
                    rounding_waste += (
                        item.allocation_capacity_bytes - item.content_length
                    )
        general = buckets["general"]
        huge = buckets["huge_reserve"]
        general["free"] = int(allocator_status["general_free_capacity_bytes"])
        huge["free"] = int(allocator_status["huge_free_capacity_bytes"])
        general_sum = sum(general.values())
        huge_sum = sum(huge.values())
        healthy = (
            general_sum == self.geometry.general_size_bytes
            and huge_sum == self.geometry.huge_reserve_bytes
            and general_sum + huge_sum == self.geometry.arena_size_bytes
        )
        if not healthy:
            self._allocation_disabled = True
        return {
            "state": "healthy" if healthy else "degraded",
            "arena_id": self.config.arena_id,
            "broker_epoch": self.broker_epoch,
            "lifecycle_state": lifecycle_state,
            "active_borrow_count": active_borrow_count,
            "close_blocked_count": close_blocked_count,
            "layout_version": _LAYOUT_VERSION,
            "layout_fingerprint": self.layout_fingerprint.hex(),
            "arena_total_bytes": self.geometry.arena_size_bytes,
            "general_total_bytes": self.geometry.general_size_bytes,
            "huge_reserved_total_bytes": self.geometry.huge_reserve_bytes,
            "general": general,
            "huge_reserve": huge,
            "free_capacity_bytes": general["free"] + huge["free"],
            "allocated_capacity_bytes": sum(
                general[name] + huge[name]
                for name in ("reserved_writing", "active", "frame_reserved")
            ),
            "published_content_bytes": published_content,
            "rounding_waste_bytes": rounding_waste,
            "frame_reserved_capacity_bytes": general["frame_reserved"],
            "revoking_capacity_bytes": general["revoking"] + huge["revoking"],
            "quarantined_capacity_bytes": (
                general["quarantined"] + huge["quarantined"]
            ),
            "largest_general_free_block_bytes": allocator_status[
                "largest_general_free_block_bytes"
            ],
            "general_external_fragmentation": allocator_status[
                "general_external_fragmentation"
            ],
            "free_blocks_by_order": allocator_status["free_blocks_by_order"],
            "allocation_failure_counts": allocator_status["allocation_failure_counts"],
        }

    @contextmanager
    def hold_writer_guard(self, descriptor_index: int) -> Iterator[None]:
        """供隔离测试和未来 SDK writer 持有指定 descriptor writer guard。"""

        with self._external_guard(self._writer_guard_offset(descriptor_index)):
            yield

    @contextmanager
    def hold_reader_guard(
        self,
        descriptor_index: int,
        *,
        reader_index: int = 0,
    ) -> Iterator[None]:
        """供隔离测试和未来 consumer 持有一个 reader guard。"""

        if not 0 <= reader_index < self.config.reader_guard_slots:
            raise ValueError("reader_index 越界")
        with self._external_guard(
            self._reader_guard_offset(descriptor_index, reader_index)
        ):
            yield

    def write_bytes(self, receipt: ArenaLeaseReceipt, content: memoryview) -> None:
        """把精确长度内容写入 receipt 指向的连续 arena extent。"""

        self._ensure_open()
        if content.nbytes != receipt.content_length:
            raise ValueError("写入长度必须等于 receipt.content_length")
        self.validate_receipt(receipt, expected_states={"writing"})
        assert self._arena_mmap is not None
        self._arena_mmap[receipt.offset : receipt.offset + receipt.content_length] = (
            content
        )
        if self.config.flush_on_write:
            self._arena_mmap.flush()

    @contextmanager
    def acquire_writer_view(
        self,
        receipt: ArenaLeaseReceipt,
    ) -> Iterator[memoryview]:
        """writer guard 后重验 descriptor，再暴露精确 writable view。"""

        with self.hold_writer_guard(receipt.descriptor_index):
            self.validate_receipt(
                receipt,
                expected_states={"writing", "frame_reserved"},
            )
            with self._borrow_arena_view(
                offset=receipt.offset,
                content_length=receipt.content_length,
            ) as view:
                yield view
            if self.config.flush_on_write:
                assert self._arena_mmap is not None
                self._arena_mmap.flush()

    @contextmanager
    def hold_frame_write_guards(
        self,
        descriptor_index: int,
    ) -> Iterator[None]:
        """frame 覆盖期间同时持有 writer 与全部 reader guards。"""

        guard_file = self._try_hold_all_external_guards(descriptor_index)
        if guard_file is None:
            raise LocalBufferArenaError("frame extent 仍由 reader 使用")
        try:
            yield
        finally:
            self._release_all_external_guards(guard_file, descriptor_index)

    def begin_frame_write(
        self,
        receipt: ArenaLeaseReceipt,
    ) -> ArenaLeaseReceipt:
        """等待读者退出后提升 frame generation，使旧 FrameRef 立即失效。"""

        with self.hold_frame_write_guards(receipt.descriptor_index):
            with self._publication_guard(receipt.descriptor_index):
                descriptor = self._require_receipt(
                    receipt,
                    expected_states={"frame_reserved"},
                )
                generation = (descriptor.descriptor_generation + 1) & ((1 << 64) - 1)
                if generation == 0:
                    generation = 1
                lease_token = token_bytes(16)
                owner_token = token_bytes(16)
                self._publish_descriptor(
                    descriptor_index=descriptor.descriptor_index,
                    state="frame_reserved",
                    descriptor_generation=generation,
                    lease_token=lease_token,
                    owner_token=owner_token,
                    extent=_descriptor_extent(descriptor),
                    deadline_ns=descriptor.deadline_ns,
                    revocation_deadline_ns=0,
                    publication_guard_held=True,
                )
        return ArenaLeaseReceipt(
            arena_id=receipt.arena_id,
            descriptor_index=receipt.descriptor_index,
            descriptor_generation=generation,
            broker_epoch=receipt.broker_epoch,
            lease_token=lease_token,
            owner_token=owner_token,
            deadline_ns=receipt.deadline_ns,
            offset=receipt.offset,
            allocation_capacity_bytes=receipt.allocation_capacity_bytes,
            content_length=receipt.content_length,
        )

    def guard_location(self, descriptor_index: int) -> dict[str, object]:
        """返回受信配置中的 guard 文件与固定 byte ranges。"""

        if not 0 <= descriptor_index < self.descriptor_count:
            raise LocalBufferArenaError("descriptor_index 越界")
        return {
            "guard_path": str(self.guard_path),
            "publication_guard_offset": self._publication_guard_offset(
                descriptor_index
            ),
            "writer_guard_offset": self._writer_guard_offset(descriptor_index),
            "reader_guard_offset": self._reader_guard_offset(descriptor_index, 0),
            "reader_guard_slots": self.config.reader_guard_slots,
        }

    @contextmanager
    def acquire_reader_view(
        self,
        receipt: ArenaLeaseReceipt,
    ) -> Iterator[memoryview]:
        """取得任一 reader guard 后重验 ACTIVE/frame descriptor。"""

        guard_file = self.guard_path.open("r+b", buffering=0)
        acquired_offset: int | None = None
        for reader_index in range(self.config.reader_guard_slots):
            offset = self._reader_guard_offset(
                receipt.descriptor_index,
                reader_index,
            )
            try:
                try_lock_byte_range_file(guard_file, offset=offset, length=1)
            except (BlockingIOError, OSError):
                continue
            acquired_offset = offset
            break
        if acquired_offset is None:
            guard_file.close()
            raise LocalBufferArenaError("LocalBuffer reader guards 已满")
        try:
            self.validate_receipt(
                receipt,
                expected_states={"active", "frame_reserved"},
            )
            with self._borrow_arena_view(
                offset=receipt.offset,
                content_length=receipt.content_length,
            ) as view:
                yield view
        finally:
            unlock_byte_range_file(guard_file, offset=acquired_offset, length=1)
            guard_file.close()

    def write_frame_bytes(
        self,
        receipt: ArenaLeaseReceipt,
        *,
        content: memoryview,
    ) -> None:
        """持有 frame 全部 guard 后覆盖已预留 extent 的有效内容。"""

        if content.nbytes <= 0 or content.nbytes > receipt.content_length:
            raise ValueError("frame 写入长度超出预留范围")
        with self.hold_frame_write_guards(receipt.descriptor_index):
            self.validate_receipt(receipt, expected_states={"frame_reserved"})
            with self._borrow_arena_view(
                offset=receipt.offset,
                content_length=content.nbytes,
            ) as view:
                view[:] = content
            if self.config.flush_on_write:
                assert self._arena_mmap is not None
                self._arena_mmap.flush()

    def close(self) -> None:
        """按可重试状态机关闭资源，并把 owner lock 保留到最后。"""

        close_deadline = monotonic() + 0.25
        with self._lifecycle:
            while self._lifecycle_state == "closing":
                remaining = close_deadline - monotonic()
                if remaining <= 0:
                    raise LocalBufferArenaCloseBusyError("arena 正由其他线程关闭")
                self._lifecycle.wait(remaining)
            if self._lifecycle_state == "closed":
                return
            self._lifecycle_state = "closing"
            while self._active_borrows > 0:
                remaining = close_deadline - monotonic()
                if remaining <= 0:
                    self._lifecycle_state = "close_blocked"
                    self._close_blocked_count += 1
                    self._lifecycle.notify_all()
                    raise LocalBufferArenaCloseBusyError(
                        f"arena 仍有 {self._active_borrows} 个 mmap view 未释放"
                    )
                self._lifecycle.wait(remaining)

        try:
            if self._allocator_mmap is not None:
                self._allocator_mmap.close()
                self._allocator_mmap = None
            if self._arena_mmap is not None:
                try:
                    self._arena_mmap.close()
                except BufferError as error:
                    raise LocalBufferArenaCloseBusyError(
                        "arena 存在未纳入借用管理的 mmap view"
                    ) from error
                self._arena_mmap = None
            if self._allocator_file is not None:
                self._allocator_file.close()
                self._allocator_file = None
            if self._arena_file is not None:
                self._arena_file.close()
                self._arena_file = None
            if self._guard_file is not None:
                self._guard_file.close()
                self._guard_file = None
            owner_lock = getattr(self, "_owner_lock", None)
            if owner_lock is not None:
                release_mmap_owner_lock(owner_lock)
                self._owner_lock = None
        except BaseException:
            with self._lifecycle:
                self._lifecycle_state = "close_blocked"
                self._close_blocked_count += 1
                self._lifecycle.notify_all()
            raise
        with self._lifecycle:
            self._closed = True
            self._lifecycle_state = "closed"
            self._lifecycle.notify_all()

    def __enter__(self) -> MmapBufferArena:
        """进入 context manager。"""

        return self

    def __exit__(self, *_args: object) -> None:
        """退出 context manager 时释放 owner。"""

        self.close()

    def _open_files(self) -> None:
        """严格创建或打开固定长度 arena/allocator 文件。"""

        metadata_size = _HEADER_SIZE + self.descriptor_count * _DESCRIPTOR_STRIDE
        self._arena_file = _open_exact_file(
            self.arena_path,
            expected_size=self.geometry.arena_size_bytes,
        )
        self._allocator_file = _open_exact_file(
            self.allocator_path,
            expected_size=metadata_size,
        )
        self._arena_mmap = mmap.mmap(
            self._arena_file.fileno(),
            self.geometry.arena_size_bytes,
        )
        self._allocator_mmap = mmap.mmap(
            self._allocator_file.fileno(),
            metadata_size,
        )

    def _ensure_open(self) -> None:
        """拒绝在关闭已经开始后建立新的 arena 操作。"""

        with self._lifecycle:
            if self._lifecycle_state != "open":
                raise LocalBufferArenaError("LocalBuffer arena 正在关闭或已经关闭")

    @contextmanager
    def _borrow_arena_view(
        self,
        *,
        offset: int,
        content_length: int,
    ) -> Iterator[memoryview]:
        """跟踪当前进程导出的 view，确保关闭不会遗留 owner lock。"""

        with self._lifecycle:
            if self._lifecycle_state != "open":
                raise LocalBufferArenaError("LocalBuffer arena 正在关闭或已经关闭")
            arena_mmap = self._arena_mmap
            if arena_mmap is None:
                raise LocalBufferArenaError("LocalBuffer arena mmap 不可用")
            self._active_borrows += 1
        view = memoryview(arena_mmap)[offset : offset + content_length]
        try:
            yield view
        finally:
            view.release()
            with self._lifecycle:
                self._active_borrows -= 1
                self._lifecycle.notify_all()

    def _initialize_or_validate_metadata(self) -> bool:
        """新文件初始化；已有文件只接受完全相同 layout。"""

        assert self._allocator_mmap is not None
        magic = bytes(self._allocator_mmap[: len(_MAGIC)])
        if magic == b"\x00" * len(_MAGIC):
            self._allocator_mmap[:] = b"\x00" * len(self._allocator_mmap)
            return False
        if magic != _MAGIC:
            raise LocalBufferArenaError("allocator metadata magic 不匹配，拒绝隐式转换")
        unpacked = _HEADER.unpack_from(self._allocator_mmap, 0)
        (
            _magic,
            version,
            header_size,
            descriptor_stride,
            descriptor_count,
            reader_guard_slots,
            guard_stride,
            arena_size,
            min_block,
            max_allocation,
            huge_reserve,
            _old_epoch,
            fingerprint,
            publication_generation,
        ) = unpacked
        if (
            version != _LAYOUT_VERSION
            or header_size != _HEADER_SIZE
            or descriptor_stride != _DESCRIPTOR_STRIDE
            or descriptor_count != self.descriptor_count
            or reader_guard_slots != self.config.reader_guard_slots
            or guard_stride != self._guard_stride
            or arena_size != self.geometry.arena_size_bytes
            or min_block != self.geometry.min_block_size_bytes
            or max_allocation != self.geometry.max_allocation_bytes
            or huge_reserve != self.geometry.huge_reserve_bytes
            or fingerprint != self.layout_fingerprint
        ):
            raise LocalBufferArenaError(
                "allocator metadata layout 不匹配，拒绝隐式转换"
            )
        self._publication_generation = publication_generation
        return True

    def _initialize_guard_file(self, *, existing: bool) -> None:
        """创建并持续持有 descriptor guards 的文件身份。"""

        expected_size = self.descriptor_count * self._guard_stride + 1
        self._guard_file = open_mmap_guard_identity(
            self.guard_path,
            expected_size=expected_size,
            create=not existing,
        )

    def _restore_descriptors(self) -> None:
        """从 descriptor 恢复所有尚未回收 extent 的 buddy 占用。"""

        for descriptor_index in range(self.descriptor_count):
            descriptor = self._read_descriptor(descriptor_index)
            if descriptor.state == "free":
                continue
            self._allocator.restore_extent(_descriptor_extent(descriptor))

    def _recover_previous_epoch(self) -> None:
        """旧 epoch lease 全部走 guard 安全回收，不能直接复用。"""

        for descriptor_index in range(self.descriptor_count):
            descriptor = self._read_descriptor(descriptor_index)
            if descriptor.state == "free":
                continue
            receipt = self._receipt_from_descriptor(descriptor)
            self.request_reclaim(receipt)

    @property
    def _guard_stride(self) -> int:
        """返回每个 descriptor 的 publication/writer/readers guard 字节数。"""

        return 2 + self.config.reader_guard_slots

    def _publication_guard_offset(self, descriptor_index: int) -> int:
        return descriptor_index * self._guard_stride

    def _writer_guard_offset(self, descriptor_index: int) -> int:
        return self._publication_guard_offset(descriptor_index) + 1

    def _reader_guard_offset(self, descriptor_index: int, reader_index: int) -> int:
        return self._publication_guard_offset(descriptor_index) + 2 + reader_index

    @contextmanager
    def _external_guard(self, offset: int) -> Iterator[None]:
        """非阻塞持有一个外部 guard byte。"""

        guard_file = self.guard_path.open("r+b", buffering=0)
        acquired = False
        try:
            try_lock_byte_range_file(guard_file, offset=offset, length=1)
            acquired = True
            yield
        finally:
            if acquired:
                unlock_byte_range_file(guard_file, offset=offset, length=1)
            guard_file.close()

    @contextmanager
    def _publication_guard(self, descriptor_index: int) -> Iterator[None]:
        """持有 descriptor 短 publication guard。"""

        if not 0 <= descriptor_index < self.descriptor_count:
            raise LocalBufferArenaError("descriptor_index 越界")
        with self._external_guard(self._publication_guard_offset(descriptor_index)):
            yield

    def _try_hold_all_external_guards(self, descriptor_index: int) -> BinaryIO | None:
        """按 writer、reader index 升序持续持有所有外部 guard。"""

        guard_file = self.guard_path.open("r+b", buffering=0)
        acquired_offsets: list[int] = []
        offsets = [self._writer_guard_offset(descriptor_index)]
        offsets.extend(
            self._reader_guard_offset(descriptor_index, reader_index)
            for reader_index in range(self.config.reader_guard_slots)
        )
        try:
            for offset in offsets:
                try_lock_byte_range_file(guard_file, offset=offset, length=1)
                acquired_offsets.append(offset)
        except (BlockingIOError, OSError):
            for offset in reversed(acquired_offsets):
                unlock_byte_range_file(guard_file, offset=offset, length=1)
            guard_file.close()
            return None
        return guard_file

    def _release_all_external_guards(
        self,
        guard_file: BinaryIO,
        descriptor_index: int,
    ) -> None:
        """逆序释放完整 writer/readers guard 集。"""

        offsets = [self._writer_guard_offset(descriptor_index)]
        offsets.extend(
            self._reader_guard_offset(descriptor_index, reader_index)
            for reader_index in range(self.config.reader_guard_slots)
        )
        for offset in reversed(offsets):
            unlock_byte_range_file(guard_file, offset=offset, length=1)
        guard_file.close()

    def _try_finalize_reclaim(
        self,
        receipt: ArenaLeaseReceipt,
        *,
        current_ns: int,
    ) -> str:
        """无等待取得外部 guards 后按 allocator->publication 顺序回收。"""

        guard_file = self._try_hold_all_external_guards(receipt.descriptor_index)
        if guard_file is None:
            with self._publication_guard(receipt.descriptor_index):
                try:
                    descriptor = self._require_receipt(
                        receipt,
                        expected_states={"revoking", "quarantined"},
                    )
                except LocalBufferArenaError:
                    return "stale"
                if (
                    descriptor.state == "revoking"
                    and current_ns >= descriptor.revocation_deadline_ns
                ):
                    self._write_descriptor_state(
                        descriptor_index=receipt.descriptor_index,
                        state="quarantined",
                    )
                    return "quarantined"
                return descriptor.state
        try:
            with self._allocator_lock:
                with self._publication_guard(receipt.descriptor_index):
                    try:
                        descriptor = self._require_receipt(
                            receipt,
                            expected_states={"revoking", "quarantined"},
                        )
                    except LocalBufferArenaError:
                        return "stale"
                    self._allocator.free(_descriptor_extent(descriptor))
                    self._publish_free_descriptor(descriptor)
                    return "released"
        finally:
            self._release_all_external_guards(
                guard_file,
                receipt.descriptor_index,
            )

    def _find_free_descriptor_locked(self) -> int:
        """选择最低 index 的 FREE descriptor。"""

        for descriptor_index in range(self.descriptor_count):
            if self._read_descriptor(descriptor_index).state == "free":
                return descriptor_index
        raise BuddyAllocationError(
            "LocalBuffer descriptor 先于 arena 容量耗尽",
            kind="integrity",
        )

    def _write_header(self) -> None:
        """在 owner 启动期一次性发布固定 metadata header。"""

        if self._allocator_mmap is None:
            return
        _HEADER.pack_into(
            self._allocator_mmap,
            0,
            _MAGIC,
            _LAYOUT_VERSION,
            _HEADER_SIZE,
            _DESCRIPTOR_STRIDE,
            self.descriptor_count,
            self.config.reader_guard_slots,
            self._guard_stride,
            self.geometry.arena_size_bytes,
            self.geometry.min_block_size_bytes,
            self.geometry.max_allocation_bytes,
            self.geometry.huge_reserve_bytes,
            self._broker_epoch_bytes,
            self.layout_fingerprint,
            self._publication_generation,
        )

    def _next_publication_generation(self) -> int:
        """在 publication lock 内生成并持久化下一诊断序号。

        broker epoch、layout 和 geometry 在 owner 生命周期内不可变，运行期不得
        再整块覆盖 header。否则不同 descriptor 的并行发布会让外部 reader 读到
        struct.pack_into 的中间态。这里只更新末尾独立的 8 字节计数。
        """

        assert self._allocator_mmap is not None
        self._publication_generation += 1
        struct.pack_into(
            "<Q",
            self._allocator_mmap,
            _HEADER.size - 8,
            self._publication_generation,
        )
        return self._publication_generation

    def _publish_descriptor(
        self,
        *,
        descriptor_index: int,
        state: ArenaLeaseState,
        descriptor_generation: int,
        lease_token: bytes,
        owner_token: bytes,
        extent: BuddyExtent,
        deadline_ns: int,
        revocation_deadline_ns: int,
        publication_guard_held: bool = False,
    ) -> None:
        """先写 descriptor body，最后发布 state。"""

        if not publication_guard_held:
            with self._publication_guard(descriptor_index):
                self._publish_descriptor(
                    descriptor_index=descriptor_index,
                    state=state,
                    descriptor_generation=descriptor_generation,
                    lease_token=lease_token,
                    owner_token=owner_token,
                    extent=extent,
                    deadline_ns=deadline_ns,
                    revocation_deadline_ns=revocation_deadline_ns,
                    publication_guard_held=True,
                )
            return
        assert self._allocator_mmap is not None
        with self._publication_lock:
            publication_generation = self._next_publication_generation()
            descriptor_offset = _descriptor_offset(descriptor_index)
            _DESCRIPTOR.pack_into(
                self._allocator_mmap,
                descriptor_offset,
                _STATE_FREE,
                _DOMAIN_HUGE_RESERVE
                if extent.domain == "huge_reserve"
                else _DOMAIN_GENERAL,
                descriptor_generation,
                lease_token,
                owner_token,
                extent.offset,
                extent.capacity_bytes,
                extent.content_length,
                deadline_ns,
                revocation_deadline_ns,
                extent.order,
                0,
                publication_generation,
            )
            struct.pack_into(
                "<I",
                self._allocator_mmap,
                descriptor_offset,
                _state_code(state),
            )

    def _write_descriptor_state(
        self,
        *,
        descriptor_index: int,
        state: ArenaLeaseState,
    ) -> None:
        """在 body 不变时最后覆盖 state publication。"""

        assert self._allocator_mmap is not None
        with self._publication_lock:
            publication_generation = self._next_publication_generation()
            descriptor_offset = _descriptor_offset(descriptor_index)
            struct.pack_into(
                "<I", self._allocator_mmap, descriptor_offset, _state_code(state)
            )
            struct.pack_into(
                "<Q",
                self._allocator_mmap,
                descriptor_offset + _DESCRIPTOR.size - 8,
                publication_generation,
            )

    def _publish_free_descriptor(self, descriptor: ArenaDescriptorSnapshot) -> None:
        """generation 提升后清空 identity，最后发布 FREE。"""

        assert self._allocator_mmap is not None
        with self._publication_lock:
            publication_generation = self._next_publication_generation()
            descriptor_offset = _descriptor_offset(descriptor.descriptor_index)
            _DESCRIPTOR.pack_into(
                self._allocator_mmap,
                descriptor_offset,
                _STATE_FREE,
                _DOMAIN_GENERAL,
                descriptor.descriptor_generation + 1,
                b"\x00" * 16,
                b"\x00" * 16,
                0,
                0,
                0,
                0,
                0,
                self.geometry.min_order,
                0,
                publication_generation,
            )

    def _read_descriptor(self, descriptor_index: int) -> ArenaDescriptorSnapshot:
        """读取一个固定 descriptor；state 是最后发布字段。"""

        if not 0 <= descriptor_index < self.descriptor_count:
            raise LocalBufferArenaError("descriptor_index 越界")
        assert self._allocator_mmap is not None
        values = _DESCRIPTOR.unpack_from(
            self._allocator_mmap,
            _descriptor_offset(descriptor_index),
        )
        (
            state_code,
            domain_code,
            generation,
            lease_token,
            owner_token,
            offset,
            capacity,
            content_length,
            deadline_ns,
            revocation_deadline_ns,
            order,
            _flags,
            publication_generation,
        ) = values
        return ArenaDescriptorSnapshot(
            descriptor_index=descriptor_index,
            state=_state_name(state_code),
            descriptor_generation=generation,
            lease_token=lease_token,
            owner_token=owner_token,
            offset=offset,
            allocation_capacity_bytes=capacity,
            content_length=content_length,
            deadline_ns=deadline_ns,
            revocation_deadline_ns=revocation_deadline_ns,
            order=order,
            domain="huge_reserve" if domain_code == _DOMAIN_HUGE_RESERVE else "general",
            publication_generation=publication_generation,
        )

    def _require_receipt(
        self,
        receipt: ArenaLeaseReceipt,
        *,
        expected_states: set[ArenaLeaseState],
    ) -> ArenaDescriptorSnapshot:
        """校验 arena、epoch、generation、token、deadline、offset 和 capacity。"""

        if receipt.arena_id != self.config.arena_id:
            raise LocalBufferArenaError("receipt arena identity 不匹配")
        if receipt.broker_epoch != self.broker_epoch:
            raise LocalBufferArenaError("receipt broker epoch 已失效")
        descriptor = self._read_descriptor(receipt.descriptor_index)
        if (
            descriptor.state not in expected_states
            or descriptor.descriptor_generation != receipt.descriptor_generation
            or descriptor.lease_token != receipt.lease_token
            or descriptor.owner_token != receipt.owner_token
            or descriptor.deadline_ns != receipt.deadline_ns
            or descriptor.offset != receipt.offset
            or descriptor.allocation_capacity_bytes != receipt.allocation_capacity_bytes
            or descriptor.content_length != receipt.content_length
        ):
            raise LocalBufferArenaError("receipt identity 或状态不匹配")
        return descriptor

    def _receipt_from_descriptor(
        self,
        descriptor: ArenaDescriptorSnapshot,
    ) -> ArenaLeaseReceipt:
        """为恢复/sweep 构造当前 owner 私有 receipt。"""

        return ArenaLeaseReceipt(
            arena_id=self.config.arena_id,
            descriptor_index=descriptor.descriptor_index,
            descriptor_generation=descriptor.descriptor_generation,
            broker_epoch=self.broker_epoch,
            lease_token=descriptor.lease_token,
            owner_token=descriptor.owner_token,
            deadline_ns=descriptor.deadline_ns,
            offset=descriptor.offset,
            allocation_capacity_bytes=descriptor.allocation_capacity_bytes,
            content_length=descriptor.content_length,
        )


class MmapBufferArenaExternalAccess:
    """在非 owner 进程中按公开 locator 安全访问固定 arena。

    该访问器只从受信任的 Broker 配置推导 mmap/guard 路径。公开
    ``BufferRef`` 与 ``BufferLease`` 不携带文件路径，也不能把任意本地文件
    注入数据面。reader/writer 必须先取得对应 guard，再在 publication guard
    内重新校验 epoch、generation、extent 和状态，随后才暴露 view。
    """

    def __init__(self, config: MmapBufferArenaConfig) -> None:
        """打开现有 arena；不取得 owner lock，也不创建或改变 layout。"""

        self.config = config
        self.geometry = config.geometry
        local_buffer_dir = config.root_dir.resolve() / "local-buffer"
        self.arena_path = local_buffer_dir / "images.mmap"
        self.allocator_path = local_buffer_dir / "state.mmap"
        self.guard_path = local_buffer_dir / "access.guard"
        self.layout_fingerprint = _build_layout_fingerprint(config)
        self._lifecycle = Condition(RLock())
        self._closed = False
        self._lifecycle_state: Literal[
            "open", "closing", "close_blocked", "closed"
        ] = "open"
        self._active_borrows = 0
        self._guard_file: BinaryIO | None = None
        self._arena_file: BinaryIO | None = None
        self._allocator_file: BinaryIO | None = None
        self._arena_mmap: mmap.mmap | None = None
        self._allocator_mmap: mmap.mmap | None = None
        expected_guard_size = self.geometry.descriptor_count * self._guard_stride + 1
        try:
            self._guard_file = open_mmap_guard_identity(
                self.guard_path,
                expected_size=expected_guard_size,
                create=False,
            )
            self._arena_file = self.arena_path.open("r+b", buffering=0)
            self._allocator_file = self.allocator_path.open("r+b", buffering=0)
            expected_metadata_size = (
                _HEADER_SIZE + self.geometry.descriptor_count * _DESCRIPTOR_STRIDE
            )
            if self.arena_path.stat().st_size != self.geometry.arena_size_bytes:
                raise LocalBufferArenaError("LocalBuffer arena 文件容量不匹配")
            if self.allocator_path.stat().st_size != expected_metadata_size:
                raise LocalBufferArenaError("LocalBuffer allocator 文件容量不匹配")
            self._arena_mmap = mmap.mmap(
                self._arena_file.fileno(),
                self.geometry.arena_size_bytes,
            )
            self._allocator_mmap = mmap.mmap(
                self._allocator_file.fileno(),
                expected_metadata_size,
            )
            self._validate_header()
        except BaseException:
            if self._allocator_mmap is not None:
                self._allocator_mmap.close()
            if self._arena_mmap is not None:
                self._arena_mmap.close()
            if self._allocator_file is not None:
                self._allocator_file.close()
            if self._arena_file is not None:
                self._arena_file.close()
            if self._guard_file is not None:
                self._guard_file.close()
            raise

    @property
    def _guard_stride(self) -> int:
        """返回每个 descriptor 的 guard byte 数。"""

        return 2 + self.config.reader_guard_slots

    def accepts_arena(self, arena_id: str) -> bool:
        """判断 locator 是否属于当前受信 arena domain。"""

        return arena_id == self.config.arena_id

    @contextmanager
    def acquire_reader_view(self, locator: object) -> Iterator[memoryview]:
        """持有 reader guard，并在 guard 内重验 locator 后返回只读 view。"""

        self._begin_borrow()
        guard_file: BinaryIO | None = None
        acquired_offset: int | None = None
        try:
            descriptor_index = int(getattr(locator, "descriptor_index"))
            guard_file = self.guard_path.open("r+b", buffering=0)
            for reader_index in range(self.config.reader_guard_slots):
                candidate = self._reader_guard_offset(
                    descriptor_index,
                    reader_index,
                )
                try:
                    try_lock_byte_range_file(
                        guard_file,
                        offset=candidate,
                        length=1,
                    )
                except (BlockingIOError, OSError):
                    continue
                acquired_offset = candidate
                break
            if acquired_offset is None:
                raise LocalBufferArenaError("LocalBuffer reader guards 已满")
            with self._publication_guard(descriptor_index):
                self._require_locator(
                    locator,
                    expected_states={"active", "frame_reserved"},
                )
            assert self._arena_mmap is not None
            view = memoryview(self._arena_mmap)[
                int(getattr(locator, "offset")) : int(getattr(locator, "offset"))
                + int(getattr(locator, "content_length"))
            ].toreadonly()
            try:
                yield view
            finally:
                view.release()
        finally:
            if acquired_offset is not None:
                unlock_byte_range_file(
                    guard_file,
                    offset=acquired_offset,
                    length=1,
                )
            if guard_file is not None:
                guard_file.close()
            self._end_borrow()

    @contextmanager
    def acquire_writer_view(self, lease: object) -> Iterator[memoryview]:
        """持有 writer guard，并在 guard 内重验 WRITING lease。"""

        self._begin_borrow()
        try:
            descriptor_index = int(getattr(lease, "descriptor_index"))
            with self._guard(self._writer_guard_offset(descriptor_index)):
                with self._publication_guard(descriptor_index):
                    self._require_locator(lease, expected_states={"writing"})
                assert self._arena_mmap is not None
                view = memoryview(self._arena_mmap)[
                    int(getattr(lease, "offset")) : int(getattr(lease, "offset"))
                    + int(getattr(lease, "content_length"))
                ]
                try:
                    yield view
                finally:
                    view.release()
        finally:
            self._end_borrow()

    def read_owned_view(self, locator: object) -> memoryview:
        """重验由当前执行持有的 locator，并返回不额外映射 arena 的只读 view。

        此入口只供已经持有 lease 所有权、且会在 owner cleanup 前释放 view 的
        Workflow 执行缓存使用。普通跨进程读取仍必须使用 acquire_reader_view，
        不能用本方法替代 reader guard。
        """

        self._begin_borrow()
        try:
            descriptor_index = int(getattr(locator, "descriptor_index"))
            with self._publication_guard(descriptor_index):
                self._require_locator(
                    locator,
                    expected_states={"active", "frame_reserved"},
                )
            assert self._arena_mmap is not None
            return memoryview(self._arena_mmap)[
                int(getattr(locator, "offset")) : int(getattr(locator, "offset"))
                + int(getattr(locator, "content_length"))
            ].toreadonly()
        finally:
            self._end_borrow()

    def close(self) -> None:
        """按可重试状态机关闭当前进程的 mmap view。"""

        close_deadline = monotonic() + 0.25
        with self._lifecycle:
            while self._lifecycle_state == "closing":
                remaining = close_deadline - monotonic()
                if remaining <= 0:
                    raise LocalBufferArenaCloseBusyError(
                        "external access 正由其他线程关闭"
                    )
                self._lifecycle.wait(remaining)
            if self._lifecycle_state == "closed":
                return
            self._lifecycle_state = "closing"
            while self._active_borrows > 0:
                remaining = close_deadline - monotonic()
                if remaining <= 0:
                    self._lifecycle_state = "close_blocked"
                    self._lifecycle.notify_all()
                    raise LocalBufferArenaCloseBusyError(
                        f"external access 仍有 {self._active_borrows} 个 view 未释放"
                    )
                self._lifecycle.wait(remaining)

        try:
            if self._allocator_mmap is not None:
                self._allocator_mmap.close()
                self._allocator_mmap = None
            if self._arena_mmap is not None:
                self._arena_mmap.close()
                self._arena_mmap = None
            if self._allocator_file is not None:
                self._allocator_file.close()
                self._allocator_file = None
            if self._arena_file is not None:
                self._arena_file.close()
                self._arena_file = None
            if self._guard_file is not None:
                self._guard_file.close()
                self._guard_file = None
        except BaseException:
            with self._lifecycle:
                self._lifecycle_state = "close_blocked"
                self._lifecycle.notify_all()
            raise
        with self._lifecycle:
            self._closed = True
            self._lifecycle_state = "closed"
            self._lifecycle.notify_all()

    def _begin_borrow(self) -> None:
        """阻止关闭与新的 external view 建立发生竞态。"""

        with self._lifecycle:
            if self._lifecycle_state != "open":
                raise LocalBufferArenaError("LocalBuffer external access 正在关闭")
            self._active_borrows += 1

    def _end_borrow(self) -> None:
        """释放 external view 借用并唤醒等待关闭的线程。"""

        with self._lifecycle:
            self._active_borrows -= 1
            self._lifecycle.notify_all()

    def _validate_header(self) -> None:
        """拒绝 magic、layout 或 arena identity 不匹配的数据面。"""

        (
            magic,
            version,
            header_size,
            descriptor_stride,
            descriptor_count,
            reader_guard_slots,
            guard_stride,
            arena_size,
            min_block,
            max_allocation,
            huge_reserve,
            _epoch,
            fingerprint,
            _publication_generation,
        ) = _HEADER.unpack_from(self._allocator_mmap, 0)
        if (
            magic != _MAGIC
            or version != _LAYOUT_VERSION
            or header_size != _HEADER_SIZE
            or descriptor_stride != _DESCRIPTOR_STRIDE
            or descriptor_count != self.geometry.descriptor_count
            or reader_guard_slots != self.config.reader_guard_slots
            or guard_stride != self._guard_stride
            or arena_size != self.geometry.arena_size_bytes
            or min_block != self.geometry.min_block_size_bytes
            or max_allocation != self.geometry.max_allocation_bytes
            or huge_reserve != self.geometry.huge_reserve_bytes
            or fingerprint != self.layout_fingerprint
        ):
            raise LocalBufferArenaError("LocalBuffer arena layout 不匹配")

    def _require_locator(
        self,
        locator: object,
        *,
        expected_states: set[ArenaLeaseState],
    ) -> ArenaDescriptorSnapshot:
        """按公开 identity 校验 descriptor，防止旧引用访问新 extent。"""

        arena_id = str(getattr(locator, "arena_id"))
        if arena_id != self.config.arena_id:
            raise LocalBufferArenaError("LocalBuffer arena identity 不匹配")
        header = _HEADER.unpack_from(self._allocator_mmap, 0)
        broker_epoch = bytes(header[11]).hex()
        locator_broker_epoch = str(getattr(locator, "broker_epoch"))
        if locator_broker_epoch != broker_epoch:
            raise LocalBufferArenaError(
                "LocalBuffer broker epoch 已失效："
                f"expected={locator_broker_epoch}, actual={broker_epoch}"
            )
        descriptor = self._read_descriptor(int(getattr(locator, "descriptor_index")))
        locator_generation = int(getattr(locator, "descriptor_generation"))
        locator_offset = int(getattr(locator, "offset"))
        locator_content_length = int(getattr(locator, "content_length"))
        locator_capacity = int(getattr(locator, "allocation_capacity_bytes"))
        content_length_matches = (
            0 < locator_content_length <= descriptor.content_length
            if descriptor.state == "frame_reserved"
            else locator_content_length == descriptor.content_length
        )
        now_ns = monotonic_ns()
        if (
            descriptor.state not in expected_states
            or descriptor.descriptor_generation != locator_generation
            or descriptor.offset != locator_offset
            or not content_length_matches
            or descriptor.allocation_capacity_bytes != locator_capacity
            or descriptor.deadline_ns <= now_ns
        ):
            raise LocalBufferArenaError(
                "LocalBuffer locator identity 或状态不匹配："
                f"expected_states={sorted(expected_states)}, "
                f"expected_generation={locator_generation}, "
                f"expected_offset={locator_offset}, "
                f"expected_capacity={locator_capacity}, "
                f"expected_content_length={locator_content_length}; "
                f"actual_state={descriptor.state}, "
                f"actual_generation={descriptor.descriptor_generation}, "
                f"actual_offset={descriptor.offset}, "
                f"actual_capacity={descriptor.allocation_capacity_bytes}, "
                f"actual_content_length={descriptor.content_length}, "
                f"actual_deadline_ns={descriptor.deadline_ns}, now_ns={now_ns}, "
                f"publication_generation={descriptor.publication_generation}"
            )
        return descriptor

    def _read_descriptor(self, descriptor_index: int) -> ArenaDescriptorSnapshot:
        """读取已发布 descriptor。"""

        if not 0 <= descriptor_index < self.geometry.descriptor_count:
            raise LocalBufferArenaError("descriptor_index 越界")
        values = _DESCRIPTOR.unpack_from(
            self._allocator_mmap,
            _descriptor_offset(descriptor_index),
        )
        (
            state_code,
            domain_code,
            generation,
            lease_token,
            owner_token,
            offset,
            capacity,
            content_length,
            deadline_ns,
            revocation_deadline_ns,
            order,
            _flags,
            publication_generation,
        ) = values
        return ArenaDescriptorSnapshot(
            descriptor_index=descriptor_index,
            state=_state_name(state_code),
            descriptor_generation=generation,
            lease_token=lease_token,
            owner_token=owner_token,
            offset=offset,
            allocation_capacity_bytes=capacity,
            content_length=content_length,
            deadline_ns=deadline_ns,
            revocation_deadline_ns=revocation_deadline_ns,
            order=order,
            domain=(
                "huge_reserve" if domain_code == _DOMAIN_HUGE_RESERVE else "general"
            ),
            publication_generation=publication_generation,
        )

    @contextmanager
    def _publication_guard(self, descriptor_index: int) -> Iterator[None]:
        """短暂持有 publication guard。"""

        with self._guard(descriptor_index * self._guard_stride):
            yield

    @contextmanager
    def _guard(self, offset: int) -> Iterator[None]:
        """非阻塞持有一个外部 guard byte。"""

        guard_file = self.guard_path.open("r+b", buffering=0)
        acquired = False
        try:
            try_lock_byte_range_file(guard_file, offset=offset, length=1)
            acquired = True
            yield
        finally:
            if acquired:
                unlock_byte_range_file(guard_file, offset=offset, length=1)
            guard_file.close()

    def _writer_guard_offset(self, descriptor_index: int) -> int:
        """返回 descriptor writer guard offset。"""

        return descriptor_index * self._guard_stride + 1

    def _reader_guard_offset(self, descriptor_index: int, reader_index: int) -> int:
        """返回 descriptor reader guard offset。"""

        return descriptor_index * self._guard_stride + 2 + reader_index


def _open_exact_file(path: Path, *, expected_size: int) -> BinaryIO:
    """只创建空文件；已有非零文件长度不一致时拒绝 truncate。"""

    try:
        handle = path.open("r+b", buffering=0)
    except FileNotFoundError:
        handle = path.open("w+b", buffering=0)
    current_size = os.fstat(handle.fileno()).st_size
    if current_size == 0:
        handle.truncate(expected_size)
    elif current_size != expected_size:
        handle.close()
        raise LocalBufferArenaError(f"{path.name} 文件长度与固定 layout 不一致")
    return handle


def _build_layout_fingerprint(config: MmapBufferArenaConfig) -> bytes:
    """为影响二进制/guard 几何的字段生成稳定 SHA-256。"""

    payload = json.dumps(
        {
            "layout_version": _LAYOUT_VERSION,
            "header_size": _HEADER_SIZE,
            "descriptor_stride": _DESCRIPTOR_STRIDE,
            "arena_id": config.arena_id,
            "arena_size_bytes": config.arena_size_bytes,
            "min_block_size_bytes": config.min_block_size_bytes,
            "max_allocation_bytes": config.max_allocation_bytes,
            "huge_reserve_bytes": config.huge_reserve_bytes,
            "reader_guard_slots": config.reader_guard_slots,
            "guard_stride": 2 + config.reader_guard_slots,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).digest()


def _descriptor_offset(descriptor_index: int) -> int:
    """返回 descriptor 在 metadata 文件中的固定偏移。"""

    return _HEADER_SIZE + descriptor_index * _DESCRIPTOR_STRIDE


def _descriptor_extent(descriptor: ArenaDescriptorSnapshot) -> BuddyExtent:
    """把 descriptor 转为 buddy allocator identity。"""

    return BuddyExtent(
        offset=descriptor.offset,
        order=descriptor.order,
        capacity_bytes=descriptor.allocation_capacity_bytes,
        content_length=descriptor.content_length,
        domain=descriptor.domain,
    )


def _state_code(state: ArenaLeaseState) -> int:
    """返回稳定二进制 state 枚举值。"""

    return {
        "free": _STATE_FREE,
        "writing": _STATE_WRITING,
        "active": _STATE_ACTIVE,
        "frame_reserved": _STATE_FRAME_RESERVED,
        "revoking": _STATE_REVOKING,
        "quarantined": _STATE_QUARANTINED,
    }[state]


def _state_name(code: int) -> ArenaLeaseState:
    """拒绝未知 descriptor state。"""

    try:
        return {
            _STATE_FREE: "free",
            _STATE_WRITING: "writing",
            _STATE_ACTIVE: "active",
            _STATE_FRAME_RESERVED: "frame_reserved",
            _STATE_REVOKING: "revoking",
            _STATE_QUARANTINED: "quarantined",
        }[code]
    except KeyError as error:
        raise LocalBufferArenaError(f"未知 descriptor state: {code}") from error
