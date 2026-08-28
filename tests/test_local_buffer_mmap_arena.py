"""LocalBuffer 固定 mmap arena 的 descriptor、guard 与恢复门禁。"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import multiprocessing
import os
from pathlib import Path
from time import monotonic_ns, sleep

import pytest

from backend.service.infrastructure.local_buffers import mmap_buffer_arena as arena_module
from backend.service.infrastructure.ipc.mmap_primitives import (
    MmapGuardFileError,
    MmapOwnerLockBusyError,
)
from backend.service.infrastructure.local_buffers.mmap_buffer_arena import (
    LocalBufferArenaCloseBusyError,
    LocalBufferArenaError,
    LocalBufferArenaIntegrityError,
    MmapBufferArena,
    MmapBufferArenaConfig,
    MmapBufferArenaExternalAccess,
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


def _hold_arena_owner(root_dir: str, ready: object) -> None:
    """子进程持有真实 arena owner，供强制终止恢复门禁使用。"""

    arena = MmapBufferArena(_config(Path(root_dir)))
    getattr(ready, "set")()
    try:
        while True:
            sleep(1)
    finally:
        arena.close()


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
        with arena.acquire_reader_view(receipt) as view:
            assert bytes(view) == payload

        assert arena.request_reclaim(receipt) == "released"
        status = arena.build_status()
        assert status["state"] == "healthy"
        assert status["free_capacity_bytes"] == 16 * _MIB


def test_descriptor_publication_never_rewrites_fixed_header(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """运行期只改单 descriptor 和计数，不能重写 epoch/layout 全局头。"""

    with MmapBufferArena(_config(tmp_path)) as arena:

        def reject_full_header_rewrite() -> None:
            raise AssertionError("descriptor publication rewrote the fixed header")

        monkeypatch.setattr(arena, "_write_header", reject_full_header_rewrite)
        receipt = arena.allocate(content_length=32, deadline_ns=_deadline())
        arena.publish_active(receipt)
        external = MmapBufferArenaExternalAccess(_config(tmp_path))
        try:
            with external.acquire_reader_view(receipt) as view:
                assert bytes(view) == b"\x00" * 32
        finally:
            external.close()
        assert arena.request_reclaim(receipt) == "released"


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


def test_existing_arena_refuses_to_recreate_missing_guard(tmp_path) -> None:
    """已有 allocator 失去 guard 身份后必须 fail-closed，不能新建第二锁域。"""

    first = MmapBufferArena(_config(tmp_path))
    guard_path = first.guard_path
    first.close()
    guard_path.unlink()

    with pytest.raises(MmapGuardFileError, match="guard 文件不存在"):
        MmapBufferArena(_config(tmp_path))
    assert not guard_path.exists()


def test_interrupted_first_initialization_can_resume_before_header_publication(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """首次 guard 创建前异常只留下未发布文件，下一 owner 可安全完成初始化。"""

    original_open = arena_module.open_mmap_guard_identity
    failed = False

    def fail_first_guard(*args, **kwargs):
        nonlocal failed
        if kwargs.get("create") and not failed:
            failed = True
            raise KeyboardInterrupt("injected guard initialization failure")
        return original_open(*args, **kwargs)

    monkeypatch.setattr(arena_module, "open_mmap_guard_identity", fail_first_guard)
    with pytest.raises(KeyboardInterrupt, match="injected guard initialization failure"):
        MmapBufferArena(_config(tmp_path))

    monkeypatch.setattr(arena_module, "open_mmap_guard_identity", original_open)
    with MmapBufferArena(_config(tmp_path)) as recovered:
        assert recovered.build_status()["state"] == "healthy"


def test_unpublished_first_initialization_repairs_partial_guard(tmp_path) -> None:
    """header 尚未发布时可修复强杀留下的短 guard，不扩大已发布布局。"""

    guard_path = tmp_path / "local-buffer" / "access.guard"
    guard_path.parent.mkdir(parents=True)
    guard_path.write_bytes(b"x")

    with MmapBufferArena(_config(tmp_path)) as arena:
        expected_size = arena.descriptor_count * (2 + arena.config.reader_guard_slots) + 1
        assert guard_path.stat().st_size == expected_size


@pytest.mark.skipif(os.name != "nt", reason="Windows 文件共享语义门禁")
def test_owner_identity_handle_blocks_guard_replacement_on_windows(tmp_path) -> None:
    """owner 存活时同名 guard 不得被删除后替换成第二锁域。"""

    arena = MmapBufferArena(_config(tmp_path))
    guard_path = arena.guard_path
    try:
        with pytest.raises(PermissionError):
            guard_path.unlink()
        assert guard_path.exists()
    finally:
        arena.close()
    guard_path.unlink()
    assert not guard_path.exists()


def test_forced_owner_process_exit_releases_arena_lock(tmp_path) -> None:
    """命令行/服务进程被强杀后，OS 释放 owner，原文件可由新 epoch 接管。"""

    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(
        target=_hold_arena_owner,
        args=(str(tmp_path), ready),
    )
    process.start()
    try:
        assert ready.wait(timeout=10)
        with pytest.raises(MmapOwnerLockBusyError):
            MmapBufferArena(_config(tmp_path))
        process.terminate()
        process.join(timeout=10)
        assert not process.is_alive()
        with MmapBufferArena(_config(tmp_path)) as recovered:
            assert recovered.build_status()["state"] == "healthy"
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=10)


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


def test_external_writer_stale_error_reports_expected_and_actual_fence(tmp_path) -> None:
    """descriptor 复用时诊断必须包含新旧 generation、状态和 publication fence。"""

    with MmapBufferArena(_config(tmp_path)) as arena:
        stale = arena.allocate(content_length=6, deadline_ns=_deadline())
        external = MmapBufferArenaExternalAccess(_config(tmp_path))
        try:
            assert arena.request_reclaim(stale) == "released"
            current = arena.allocate(content_length=6, deadline_ns=_deadline())
            assert current.descriptor_index == stale.descriptor_index
            with pytest.raises(
                LocalBufferArenaError,
                match=(
                    r"expected_generation=.*actual_generation=.*"
                    r"publication_generation="
                ),
            ):
                with external.acquire_writer_view(stale):
                    pass
            assert arena.request_reclaim(current) == "released"
        finally:
            external.close()


def test_close_waits_for_borrow_and_remains_retryable(tmp_path) -> None:
    """未释放 view 只阻止当前关闭；释放后可重试且 owner lock 最后释放。"""

    arena = MmapBufferArena(_config(tmp_path))
    receipt = arena.allocate(content_length=6, deadline_ns=_deadline())
    arena.publish_active(receipt)
    reader = arena.acquire_reader_view(receipt)
    view = reader.__enter__()
    try:
        with pytest.raises(LocalBufferArenaCloseBusyError):
            arena.close()
        blocked_status = arena.build_status()
        assert blocked_status["lifecycle_state"] == "close_blocked"
        assert blocked_status["active_borrow_count"] == 1
        assert blocked_status["close_blocked_count"] == 1
        with pytest.raises(LocalBufferArenaError):
            arena.allocate(content_length=1, deadline_ns=_deadline())
        with pytest.raises(MmapOwnerLockBusyError):
            MmapBufferArena(_config(tmp_path))
    finally:
        reader.__exit__(None, None, None)

    arena.close()
    with MmapBufferArena(_config(tmp_path)):
        pass
    with pytest.raises(ValueError):
        bytes(view)


def test_external_access_close_is_retryable_while_view_is_borrowed(tmp_path) -> None:
    """非 owner mapping 同样不能因活动 view 关闭失败而遗失文件 handle。"""

    with MmapBufferArena(_config(tmp_path)) as arena:
        receipt = arena.allocate(content_length=4, deadline_ns=_deadline())
        arena.publish_active(receipt)
        external = MmapBufferArenaExternalAccess(_config(tmp_path))
        reader = external.acquire_reader_view(receipt)
        reader.__enter__()
        try:
            with pytest.raises(LocalBufferArenaCloseBusyError):
                external.close()
        finally:
            reader.__exit__(None, None, None)
        external.close()


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


def test_batch_handoff_rolls_back_mid_write_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第二个 descriptor 写入异常时恢复整批旧 owner/deadline。"""

    with MmapBufferArena(_config(tmp_path)) as arena:
        first = arena.allocate(content_length=10, deadline_ns=_deadline())
        second = arena.allocate(content_length=20, deadline_ns=_deadline())
        arena.publish_active(first)
        arena.publish_active(second)
        original_publish = arena._publish_descriptor
        call_count = 0

        def fail_second_publish(**kwargs) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("injected descriptor write failure")
            original_publish(**kwargs)

        monkeypatch.setattr(arena, "_publish_descriptor", fail_second_publish)
        with pytest.raises(LocalBufferArenaError, match="已回滚全部 descriptor"):
            arena.transfer_owners_batch(
                (first, second),
                new_deadline_ns=_deadline(),
            )
        arena.validate_receipt(first, expected_states={"active"})
        arena.validate_receipt(second, expected_states={"active"})


def test_batch_handoff_quarantines_rollback_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """写入和回滚都失败时把对应 lease 收敛到 REVOKING。"""

    with MmapBufferArena(_config(tmp_path)) as arena:
        first = arena.allocate(content_length=10, deadline_ns=_deadline())
        second = arena.allocate(content_length=20, deadline_ns=_deadline())
        arena.publish_active(first)
        arena.publish_active(second)
        original_publish = arena._publish_descriptor
        call_count = 0

        def fail_write_and_one_rollback(**kwargs) -> None:
            nonlocal call_count
            call_count += 1
            if call_count in {2, 3}:
                raise OSError("injected persistent descriptor failure")
            original_publish(**kwargs)

        monkeypatch.setattr(
            arena,
            "_publish_descriptor",
            fail_write_and_one_rollback,
        )
        with pytest.raises(
            LocalBufferArenaIntegrityError,
            match="进入 REVOKING",
        ):
            arena.transfer_owners_batch(
                (first, second),
                new_deadline_ns=_deadline(),
            )
        arena.validate_receipt(first, expected_states={"active"})
        arena.validate_receipt(second, expected_states={"revoking"})


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
