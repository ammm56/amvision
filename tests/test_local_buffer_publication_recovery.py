"""真实 publication 竞争不能删除有效 lease 或误报成功释放。"""

from contextlib import contextmanager
import multiprocessing
from time import monotonic_ns

import pytest

from backend.service.application.errors import InvalidRequestError, OperationTimeoutError
from backend.service.infrastructure.ipc.mmap_primitives import MmapGuardBusyError
from tests.test_local_buffer_arena_pool import _pool, _MIB
from tests.test_local_buffer_broker_phase1 import _supervisor
from tests.test_local_buffer_mmap_arena import _hold_publication_byte


@contextmanager
def _hold_guard(path, offset):
    """只持有本次创建的 guard，并确定性回收测试子进程。"""
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    holder = context.Process(target=_hold_publication_byte, args=(str(path), offset, ready, release))
    holder.start()
    try:
        assert ready.wait(10)
        yield
    finally:
        release.set()
        holder.join(5)
        if holder.is_alive():
            holder.terminate()
            holder.join(5)
    assert holder.exitcode == 0


@pytest.mark.parametrize("action", ["sweep", "release", "conditional_release", "read"])
def test_busy_publication_preserves_live_lease(tmp_path, action):
    """无 TTL lease 超时后仍可读和回收，不能靠到期清理掩盖丢失。"""
    with _pool(tmp_path) as pool:
        lease = pool.allocate(content_length=6, owner_kind="test", owner_id="publication")
        pool.write_lease_bytes(lease=lease, content=memoryview(b"BGR24!"))
        result = pool.commit_lease(lease=lease, media_type="image/png")
        record = pool._records[lease.lease_id]
        receipt = pool._build_receipt(record)
        with _hold_guard(receipt.guard_path, receipt.publication_guard_offset):
            if action == "sweep":
                pool.sweep_reclaiming_leases()
            else:
                with pytest.raises(MmapGuardBusyError):
                    if action == "release":
                        pool.release(lease.lease_id)
                    elif action == "conditional_release":
                        pool.conditional_release(receipt=receipt)
                    else:
                        pool.read_buffer_ref(result.buffer_ref)
            assert pool._records[lease.lease_id] is record
        pool.sweep_reclaiming_leases()
        assert pool.read_buffer_ref(result.buffer_ref) == b"BGR24!"
        assert pool.conditional_release(receipt=receipt) == "released"
        assert pool.build_status()["free_capacity_bytes"] == 16 * _MIB
        assert pool.conditional_release(receipt=receipt) == "stale"


def test_sweep_retries_busy_expired_descriptor(tmp_path):
    """到期回收跳过竞争项，仍处理其他项，下一轮恢复全部容量。"""
    with _pool(tmp_path) as pool:
        first = pool.allocate(content_length=6, owner_kind="test", owner_id="first")
        second = pool.allocate(content_length=6, owner_kind="test", owner_id="second")
        receipt = pool._build_receipt(pool._records[first.lease_id])
        with _hold_guard(receipt.guard_path, receipt.publication_guard_offset):
            pool.sweep_reclaiming_leases(now_ns=(1 << 63) - 1)
            assert first.lease_id in pool._records
            assert second.lease_id not in pool._records
        pool.sweep_reclaiming_leases(now_ns=(1 << 63) - 1)
        assert not pool._records
        assert pool.build_status()["free_capacity_bytes"] == 16 * _MIB


def test_broker_timeout_preserves_client_receipt(tmp_path):
    """跨进程响应保留 timeout 类型和 writer locator，重试可完成释放。"""
    supervisor = _supervisor(tmp_path)
    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None
        allocation = client.allocate_external_buffer(
            content_length=6, owner_kind="test", owner_id="publication",
            deadline_ns=monotonic_ns() + 30_000_000_000,
        )
        receipt = allocation.receipt
        with _hold_guard(receipt.guard_path, receipt.publication_guard_offset):
            with pytest.raises(OperationTimeoutError) as caught:
                client.conditional_release(receipt=receipt)
            assert caught.value.code == "operation_timeout"
            assert receipt.lease_id in client._writer_locations
        assert client.conditional_release(receipt=receipt) == "released"
        assert receipt.lease_id not in client._writer_locations
        assert client.get_status()["free_capacity_bytes"] == 16 * _MIB
    finally:
        supervisor.stop()


@pytest.mark.parametrize("blocked_index", [0, 1])
def test_frame_channel_destroy_retains_retry_identity(tmp_path, blocked_index):
    """部分回收超时保留关闭状态和完整凭据，禁止新写入，重试回收全部容量。"""
    with _pool(tmp_path) as pool:
        pool.create_frame_channel(stream_id="test", frame_count=2, max_frame_content_length=6)
        receipt = pool._channels["test"].receipts[blocked_index]
        offset = receipt.descriptor_index * (2 + pool.config.reader_guard_slots)
        with _hold_guard(pool.arena.guard_path, offset):
            with pytest.raises(MmapGuardBusyError):
                pool.destroy_frame_channel(stream_id="test")
            assert pool._channels["test"].closing
            with pytest.raises(InvalidRequestError, match="正在销毁"):
                pool.allocate_frame(stream_id="test", content_length=6)
        assert pool.destroy_frame_channel(stream_id="test") == 2
        assert pool.build_status()["frame_channel_count"] == 0
        assert pool.build_status()["free_capacity_bytes"] == 16 * _MIB
