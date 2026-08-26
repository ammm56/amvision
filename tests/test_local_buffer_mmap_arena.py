"""LocalBuffer 固定 mmap arena 的 descriptor、guard 与恢复门禁。"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from time import monotonic_ns

import pytest

from backend.service.infrastructure.local_buffers.mmap_buffer_arena import (
    LocalBufferArenaError,
    MmapBufferArena,
    MmapBufferArenaConfig,
)
from backend.service.infrastructure.local_buffers.buddy_allocator import (
    BuddyAllocationError,
)


_MIB = 1024 * 1024


def _config(tmp_path, **changes: object) -> MmapBufferArenaConfig:
    """构造小容量但与正式 layout 规则一致的测试 arena。"""

    config = MmapBufferArenaConfig(
        root_dir=tmp_path,
        arena_id="local-buffer-main",
        arena_size_bytes=16 * _MIB,
        min_block_size_bytes=_MIB,
        max_allocation_bytes=8 * _MIB,
        reader_guard_slots=4,
        revocation_grace_seconds=0.01,
    )
    return replace(config, **changes)


def _deadline(seconds: float = 5.0) -> int:
    """生成测试用后端 monotonic deadline。"""

    return monotonic_ns() + int(seconds * 1_000_000_000)


def test_arena_allocates_exact_extent_and_publishes_active_bytes(tmp_path) -> None:
    """descriptor body、连续 extent、写入和 ACTIVE publication 保持一致。"""

    with MmapBufferArena(_config(tmp_path)) as arena:
        payload = memoryview(b"arena-payload")
        receipt = arena.allocate(
            content_length=payload.nbytes,
            deadline_ns=_deadline(),
        )
        assert receipt.offset == 0
        assert receipt.allocation_capacity_bytes == _MIB
        assert arena.descriptor_snapshot(receipt.descriptor_index).state == "writing"

        with arena.hold_writer_guard(receipt.descriptor_index):
            arena.write_bytes(receipt, payload)
        arena.publish_active(receipt)
        with arena.hold_reader_guard(receipt.descriptor_index):
            view = arena.read_view(receipt)
            try:
                assert bytes(view) == payload
            finally:
                view.release()

        assert arena.request_reclaim(receipt) == "released"
        status = arena.build_status()
        assert status["state"] == "healthy"
        assert status["free_capacity_bytes"] == 16 * _MIB


def test_reclaim_holds_all_guards_and_quarantines_blocked_reader(tmp_path) -> None:
    """reader 未释放时不能 FREE/merge，超过 grace 后进入 QUARANTINED。"""

    with MmapBufferArena(_config(tmp_path)) as arena:
        receipt = arena.allocate(content_length=10, deadline_ns=_deadline())
        arena.publish_active(receipt)
        with arena.hold_reader_guard(receipt.descriptor_index):
            assert arena.request_reclaim(receipt) == "revoking"
            state = arena.descriptor_snapshot(receipt.descriptor_index)
            assert state.state == "revoking"
            assert (
                arena.request_reclaim(
                    receipt,
                    now_ns=state.revocation_deadline_ns + 1,
                )
                == "quarantined"
            )
            assert arena.build_status()["quarantined_capacity_bytes"] == _MIB

        assert arena.request_reclaim(receipt) == "released"
        assert arena.build_status()["free_capacity_bytes"] == 16 * _MIB


def test_reclaim_requires_writer_and_every_reader_guard(tmp_path) -> None:
    """WRITING/ACTIVE 都不能只探测一个 guard 后立即复用 extent。"""

    with MmapBufferArena(_config(tmp_path)) as arena:
        writing = arena.allocate(content_length=10, deadline_ns=_deadline())
        with arena.hold_writer_guard(writing.descriptor_index):
            assert arena.request_reclaim(writing) == "revoking"
        assert arena.request_reclaim(writing) == "released"

        active = arena.allocate(content_length=10, deadline_ns=_deadline())
        arena.publish_active(active)
        with ExitStack() as stack:
            stack.enter_context(
                arena.hold_reader_guard(active.descriptor_index, reader_index=0)
            )
            stack.enter_context(
                arena.hold_reader_guard(active.descriptor_index, reader_index=3)
            )
            assert arena.request_reclaim(active) == "revoking"
        assert arena.request_reclaim(active) == "released"


def test_restart_reclaims_unguarded_old_epoch_and_rejects_old_receipt(tmp_path) -> None:
    """Broker 重启更新 epoch；无 guard 的旧 lease 安全回收。"""

    first = MmapBufferArena(_config(tmp_path))
    old_receipt = first.allocate(content_length=2 * _MIB, deadline_ns=_deadline())
    first.publish_active(old_receipt)
    old_epoch = first.broker_epoch
    first.close()

    with MmapBufferArena(_config(tmp_path)) as recovered:
        assert recovered.broker_epoch != old_epoch
        assert recovered.build_status()["free_capacity_bytes"] == 16 * _MIB
        with pytest.raises(LocalBufferArenaError):
            recovered.validate_receipt(old_receipt, expected_states={"active"})


def test_restart_keeps_guarded_extent_revoking_until_guard_released(tmp_path) -> None:
    """旧进程 reader 存活时新 Broker 不得复用对应 extent。"""

    first = MmapBufferArena(_config(tmp_path))
    receipt = first.allocate(content_length=2 * _MIB, deadline_ns=_deadline())
    first.publish_active(receipt)
    reader_guard = first.hold_reader_guard(receipt.descriptor_index)
    reader_guard.__enter__()
    first.close()
    recovered = MmapBufferArena(_config(tmp_path))
    try:
        assert (
            recovered.descriptor_snapshot(receipt.descriptor_index).state == "revoking"
        )
        assert recovered.build_status()["revoking_capacity_bytes"] == 2 * _MIB
        reader_guard.__exit__(None, None, None)
        summary = recovered.sweep(now_ns=_deadline())
        assert summary["released_count"] == 1
        assert recovered.build_status()["free_capacity_bytes"] == 16 * _MIB
    finally:
        recovered.close()


def test_layout_mismatch_refuses_start_without_truncating_files(tmp_path) -> None:
    """已有 metadata 几何不匹配时拒绝隐式转换和 truncate。"""

    first = MmapBufferArena(_config(tmp_path))
    allocator_path = first.allocator_path
    original_size = allocator_path.stat().st_size
    first.close()

    incompatible = _config(
        tmp_path,
        min_block_size_bytes=2 * _MIB,
        max_allocation_bytes=8 * _MIB,
    )
    with pytest.raises(LocalBufferArenaError):
        MmapBufferArena(incompatible)
    assert allocator_path.stat().st_size == original_size


def test_health_capacity_conservation_in_all_descriptor_states(tmp_path) -> None:
    """general/reserve 分域和 arena 总量对所有状态严格守恒。"""

    config = _config(tmp_path, huge_reserve_bytes=8 * _MIB)
    with MmapBufferArena(config) as arena:
        writing = arena.allocate(content_length=_MIB + 1, deadline_ns=_deadline())
        active = arena.allocate(content_length=3 * _MIB, deadline_ns=_deadline())
        arena.publish_active(active)
        huge = arena.allocate(content_length=8 * _MIB, deadline_ns=_deadline())
        arena.publish_active(huge)

        status = arena.build_status()
        general = status["general"]
        reserve = status["huge_reserve"]
        assert sum(general.values()) == status["general_total_bytes"]
        assert sum(reserve.values()) == status["huge_reserved_total_bytes"]
        assert status["arena_total_bytes"] == (
            status["general_total_bytes"] + status["huge_reserved_total_bytes"]
        )
        assert status["rounding_waste_bytes"] == 2 * _MIB - 1
        assert status["state"] == "healthy"

        assert arena.request_reclaim(writing) == "released"
        assert arena.request_reclaim(active) == "released"
        assert arena.request_reclaim(huge) == "released"


def test_direct_writer_and_reader_views_revalidate_after_guard(tmp_path) -> None:
    """Python direct view 在取得 guard 后重验 identity 且不建立整图 bytes。"""

    with MmapBufferArena(_config(tmp_path)) as arena:
        receipt = arena.allocate(content_length=6, deadline_ns=_deadline())
        with arena.acquire_writer_view(receipt) as writer:
            writer[:] = b"BGR24!"
        arena.publish_active(receipt)
        with arena.acquire_reader_view(receipt) as reader:
            assert bytes(reader) == b"BGR24!"

        transferred = arena.transfer_owner(receipt, new_deadline_ns=_deadline())
        with pytest.raises(LocalBufferArenaError):
            with arena.acquire_reader_view(receipt):
                pass
        with arena.acquire_reader_view(transferred) as reader:
            assert bytes(reader) == b"BGR24!"
        assert arena.request_reclaim(transferred) == "released"


def test_batch_handoff_is_all_or_nothing(tmp_path) -> None:
    """任一旧 receipt 失效时，整批输出 owner/deadline 都不改变。"""

    with MmapBufferArena(_config(tmp_path)) as arena:
        first = arena.allocate(content_length=10, deadline_ns=_deadline())
        second = arena.allocate(content_length=20, deadline_ns=_deadline())
        arena.publish_active(first)
        arena.publish_active(second)
        stale_second = replace(second, owner_token=b"x" * 16)

        with pytest.raises(LocalBufferArenaError):
            arena.transfer_owners_batch(
                (first, stale_second),
                new_deadline_ns=_deadline(),
            )
        arena.validate_receipt(first, expected_states={"active"})
        arena.validate_receipt(second, expected_states={"active"})

        transferred = arena.transfer_owners_batch(
            (first, second),
            new_deadline_ns=_deadline(),
        )
        assert len(transferred) == 2
        assert transferred[0].owner_token != first.owner_token
        assert transferred[1].owner_token != second.owner_token
        assert arena.request_reclaim(transferred[0]) == "released"
        assert arena.request_reclaim(transferred[1]) == "released"


def test_frame_channel_allocation_is_all_or_nothing(tmp_path) -> None:
    """第 N 个 extent 分配失败时回滚前面全部 descriptor/容量。"""

    with MmapBufferArena(_config(tmp_path)) as arena:
        with pytest.raises(BuddyAllocationError):
            arena.allocate_frame_channel(
                frame_count=3,
                max_frame_content_length=7 * _MIB,
                deadline_ns=_deadline(),
            )
        status = arena.build_status()
        assert status["frame_reserved_capacity_bytes"] == 0
        assert status["free_capacity_bytes"] == 16 * _MIB

        channel = arena.allocate_frame_channel(
            frame_count=4,
            max_frame_content_length=_MIB,
            deadline_ns=_deadline(),
        )
        assert len(channel) == 4
        assert arena.build_status()["frame_reserved_capacity_bytes"] == 4 * _MIB
        assert arena.destroy_frame_channel(channel) == ("released",) * 4
