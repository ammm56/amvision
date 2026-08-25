"""LocalBuffer external producer lease、guard 与 owner handoff 测试。"""

from __future__ import annotations

import mmap
from pathlib import Path
from time import monotonic_ns

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.local_buffers import (
    LocalBufferBrokerPoolSettings,
    LocalBufferBrokerProcessSupervisor,
    LocalBufferBrokerSettings,
)
from backend.service.infrastructure.ipc.mmap_primitives import (
    acquire_mmap_guard,
    crc32_ieee,
)
from backend.service.infrastructure.local_buffers import (
    MmapBufferPool,
    MmapBufferPoolConfig,
)


def test_external_writer_guard_checksum_and_exact_length_commit(tmp_path: Path) -> None:
    """验证 external writer 必须先释放 guard，且按精确长度校验 CRC32。"""

    content = b"external-bgr24-payload"
    with _build_pool(tmp_path) as pool:
        deadline_ns = monotonic_ns() + 5_000_000_000
        allocation = pool.allocate_external(
            size=len(content),
            owner_kind="workflow-trigger-write",
            owner_id="trigger-source-1:request-1",
            deadline_ns=deadline_ns,
        )

        with acquire_mmap_guard(
            guard_path=allocation.receipt.writer_guard_path,
            deadline_ns=deadline_ns,
            poll_interval_seconds=0.001,
        ):
            _write_lease_bytes(
                file_path=Path(allocation.lease.file_path),
                offset=allocation.lease.offset,
                content=content,
            )
            with pytest.raises(
                InvalidRequestError,
                match="writer guard 仍由写入方持有",
            ):
                pool.commit_external_lease(
                    receipt=allocation.receipt,
                    checksum_algorithm=1,
                    checksum=crc32_ieee(content),
                    media_type="image/raw",
                    shape=(1, len(content), 1),
                    dtype="uint8",
                    layout="HWC",
                    pixel_format="GRAY",
                )

        with pytest.raises(InvalidRequestError, match="checksum 校验失败"):
            pool.commit_external_lease(
                receipt=allocation.receipt,
                checksum_algorithm=1,
                checksum=crc32_ieee(content) ^ 0xFFFFFFFF,
                media_type="image/raw",
            )

        result = pool.commit_external_lease(
            receipt=allocation.receipt,
            checksum_algorithm=1,
            checksum=crc32_ieee(content),
            media_type="image/raw",
            shape=(1, len(content), 1),
            dtype="uint8",
            layout="HWC",
            pixel_format="GRAY",
        )

        assert result.lease.state == "active"
        assert result.buffer_ref.size == len(content)
        assert pool.read_buffer_ref(result.buffer_ref) == content


def test_external_commit_and_first_owner_handoff_are_atomic(tmp_path: Path) -> None:
    """验证 external commit 与首次 owner handoff 只发布一个 ACTIVE 状态。"""

    content = b"atomic-external-handoff"
    with _build_pool(tmp_path) as pool:
        writer_deadline_ns = monotonic_ns() + 5_000_000_000
        allocation = pool.allocate_external(
            size=len(content),
            owner_kind="workflow-trigger-write",
            owner_id="trigger-source-1:request-atomic",
            deadline_ns=writer_deadline_ns,
        )
        with acquire_mmap_guard(
            guard_path=allocation.receipt.writer_guard_path,
            deadline_ns=writer_deadline_ns,
            poll_interval_seconds=0.001,
        ):
            _write_lease_bytes(
                file_path=Path(allocation.lease.file_path),
                offset=allocation.lease.offset,
                content=content,
            )

        runtime_deadline_ns = monotonic_ns() + 5_000_000_000
        result = pool.publish_external_lease_and_transfer(
            receipt=allocation.receipt,
            media_type="application/octet-stream",
            new_owner_kind="workflow-runtime",
            new_owner_id="workflow-run-1:runtime-1:request-atomic",
            deadline_ns=runtime_deadline_ns,
        )

        assert result.lease.state == "active"
        assert result.lease.owner_kind == "workflow-runtime"
        assert result.receipt.owner_id == result.lease.owner_id
        assert result.receipt.deadline_ns == runtime_deadline_ns
        assert pool.read_buffer_ref(result.buffer_ref) == content
        assert pool.conditional_release(receipt=allocation.receipt) == "stale"
        assert pool.conditional_release(receipt=result.receipt) == "released"


def test_external_publish_handoff_rejects_active_writer_and_keeps_receipt_valid(
    tmp_path: Path,
) -> None:
    """验证 writer 未释放时不发布 ACTIVE owner，原 receipt 仍可补偿。"""

    content = b"active-writer-must-not-transfer"
    with _build_pool(tmp_path) as pool:
        deadline_ns = monotonic_ns() + 5_000_000_000
        allocation = pool.allocate_external(
            size=len(content),
            owner_kind="workflow-trigger-write",
            owner_id="trigger-source-1:request-active-writer",
            deadline_ns=deadline_ns,
        )
        with acquire_mmap_guard(
            guard_path=allocation.receipt.writer_guard_path,
            deadline_ns=deadline_ns,
            poll_interval_seconds=0.001,
        ):
            _write_lease_bytes(
                file_path=Path(allocation.lease.file_path),
                offset=allocation.lease.offset,
                content=content,
            )
            with pytest.raises(
                InvalidRequestError,
                match="writer guard 仍由写入方持有",
            ):
                pool.publish_external_lease_and_transfer(
                    receipt=allocation.receipt,
                    media_type="application/octet-stream",
                    new_owner_kind="workflow-runtime",
                    new_owner_id="workflow-run-invalid",
                    deadline_ns=monotonic_ns() + 5_000_000_000,
                )

        result = pool.publish_external_lease_and_transfer(
            receipt=allocation.receipt,
            media_type="application/octet-stream",
            new_owner_kind="workflow-runtime",
            new_owner_id="workflow-run-active-writer",
            deadline_ns=monotonic_ns() + 5_000_000_000,
        )

        assert result.lease.state == "active"
        assert pool.read_buffer_ref(result.buffer_ref) == content
        assert pool.conditional_release(receipt=allocation.receipt) == "stale"
        assert pool.conditional_release(receipt=result.receipt) == "released"


def test_owner_handoff_is_batch_atomic_and_stale_receipt_cannot_release(
    tmp_path: Path,
) -> None:
    """验证 batch CAS、旧 owner receipt fencing 和槽位复用 generation。"""

    with _build_pool(tmp_path, slot_count=2) as pool:
        first = _write_external(pool, b"first", request_id="request-1")
        second = _write_external(pool, b"second", request_id="request-2")
        stale_second = second.receipt.model_copy(
            update={"generation": second.receipt.generation + 1}
        )
        handoff_deadline_ns = monotonic_ns() + 5_000_000_000

        with pytest.raises(InvalidRequestError, match="identity 不匹配"):
            pool.transfer_ownership_batch(
                receipts=(first.receipt, stale_second),
                new_owner_kind="workflow-runtime",
                new_owner_id="workflow-run-1",
                deadline_ns=handoff_deadline_ns,
            )

        # 失败批次不得部分更新 first；原 owner receipt 仍能组成成功批次。
        transferred = pool.transfer_ownership_batch(
            receipts=(first.receipt, second.receipt),
            new_owner_kind="workflow-runtime",
            new_owner_id="workflow-run-1",
            deadline_ns=handoff_deadline_ns,
        )

        assert {item.owner_kind for item in transferred} == {"workflow-runtime"}
        assert {item.owner_id for item in transferred} == {"workflow-run-1"}
        assert pool.conditional_release(receipt=first.receipt) == "stale"
        assert pool.build_status()["used_count"] == 2
        assert pool.conditional_release(receipt=transferred[0]) == "released"

        replacement = pool.allocate_external(
            size=4,
            owner_kind="workflow-trigger-write",
            owner_id="trigger-source-1:request-3",
            deadline_ns=monotonic_ns() + 5_000_000_000,
        )
        assert replacement.receipt.generation > first.receipt.generation
        assert pool.conditional_release(receipt=first.receipt) == "stale"
        assert pool.build_status()["used_count"] == 2


def test_external_writer_deadline_revoke_quarantine_and_reclaim(tmp_path: Path) -> None:
    """验证 writer 崩溃时不阻塞 broker，并经 REVOKING/QUARANTINED 回收。"""

    with _build_pool(tmp_path, revocation_grace_seconds=0.001) as pool:
        base_ns = monotonic_ns()
        allocation = pool.allocate_external(
            size=16,
            owner_kind="workflow-trigger-write",
            owner_id="trigger-source-1:request-timeout",
            deadline_ns=base_ns + 10_000_000,
        )
        with acquire_mmap_guard(
            guard_path=allocation.receipt.writer_guard_path,
            deadline_ns=base_ns + 5_000_000_000,
            poll_interval_seconds=0.001,
        ):
            first = pool.sweep_reclaiming_leases(now_ns=base_ns + 11_000_000)
            second = pool.sweep_reclaiming_leases(now_ns=base_ns + 12_000_000)

            status = pool.build_status()
            assert first == {"released_count": 0, "quarantined_count": 0}
            assert second == {"released_count": 0, "quarantined_count": 1}
            assert status["quarantined_count"] == 1
            with pytest.raises(InvalidRequestError, match="pool 已满"):
                pool.allocate(
                    size=1,
                    owner_kind="test",
                    owner_id="must-not-reuse-quarantined",
                )

        reclaimed = pool.sweep_reclaiming_leases(now_ns=base_ns + 13_000_000)
        assert reclaimed == {"released_count": 1, "quarantined_count": 0}
        assert pool.build_status()["free_count"] == 1


def test_active_reader_guard_prevents_slot_reuse_until_reader_exits(
    tmp_path: Path,
) -> None:
    """验证 ACTIVE 输出有 reader 时只能撤销隔离，不能提前复用槽位。"""

    with _build_pool(tmp_path, revocation_grace_seconds=0.001) as pool:
        active = _write_external(pool, b"response-image", request_id="response-1")
        base_ns = monotonic_ns()
        reader_deadline_ns = base_ns + 5_000_000_000
        with acquire_mmap_guard(
            guard_path=active.receipt.reader_guard_path,
            deadline_ns=reader_deadline_ns,
            poll_interval_seconds=0.001,
            offset=7,
            length=1,
        ):
            assert (
                pool.conditional_release(
                    receipt=active.receipt,
                    now_ns=base_ns,
                )
                == "revoking"
            )
            assert pool.sweep_reclaiming_leases(
                now_ns=base_ns + 2_000_000
            ) == {"released_count": 0, "quarantined_count": 1}
            assert pool.build_status()["free_count"] == 0

        assert pool.sweep_reclaiming_leases(
            now_ns=base_ns + 3_000_000
        ) == {"released_count": 1, "quarantined_count": 0}
        assert pool.build_status()["free_count"] == 1


def test_broker_process_external_lease_and_cross_pool_batch_handoff(
    tmp_path: Path,
) -> None:
    """验证新协议经 companion process 序列化后仍保持跨 pool 批次原子语义。"""

    slot_size_bytes = 4096
    settings = LocalBufferBrokerSettings(
        root_dir=str(tmp_path / "buffers"),
        default_pool_name="image-a",
        request_timeout_seconds=5.0,
        pools=(
            LocalBufferBrokerPoolSettings(
                pool_name="image-a",
                slot_size_bytes=slot_size_bytes,
                slot_count=1,
            ),
            LocalBufferBrokerPoolSettings(
                pool_name="image-b",
                slot_size_bytes=slot_size_bytes,
                slot_count=1,
            ),
        ),
    )
    supervisor = LocalBufferBrokerProcessSupervisor(settings=settings)
    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None
        first = _write_external_with_client(client, b"pool-a", pool_name="image-a")
        second = _write_external_with_client(client, b"pool-b", pool_name="image-b")
        stale_second = second.receipt.model_copy(
            update={"owner_id": "wrong-owner"}
        )

        with pytest.raises(InvalidRequestError, match="identity 不匹配"):
            client.transfer_lease_ownership(
                receipts=(first.receipt, stale_second),
                new_owner_kind="workflow-runtime",
                new_owner_id="workflow-run-process",
                deadline_ns=monotonic_ns() + 5_000_000_000,
            )

        transferred = client.transfer_lease_ownership(
            receipts=(first.receipt, second.receipt),
            new_owner_kind="workflow-runtime",
            new_owner_id="workflow-run-process",
            deadline_ns=monotonic_ns() + 5_000_000_000,
        )
        assert [item.pool_name for item in transferred] == ["image-a", "image-b"]
        assert client.conditional_release(receipt=first.receipt) == "stale"
        assert [client.conditional_release(receipt=item) for item in transferred] == [
            "released",
            "released",
        ]
    finally:
        supervisor.stop()


def test_broker_client_reader_guard_blocks_release_until_reader_exits(
    tmp_path: Path,
) -> None:
    """验证正式 client 在加锁后二次校验，并阻止 ACTIVE 槽位提前复用。"""

    settings = LocalBufferBrokerSettings(
        root_dir=str(tmp_path / "buffers"),
        default_pool_name="image",
        request_timeout_seconds=5.0,
        pools=(
            LocalBufferBrokerPoolSettings(
                pool_name="image",
                slot_size_bytes=4096,
                slot_count=1,
            ),
        ),
    )
    supervisor = LocalBufferBrokerProcessSupervisor(settings=settings)
    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None
        content = b"reader-guard-content"
        deadline_ns = monotonic_ns() + 5_000_000_000
        active = client.allocate_external_buffer(
            size=len(content),
            owner_kind="workflow-trigger-write",
            owner_id="reader-guard-test",
            deadline_ns=deadline_ns,
            pool_name="image",
        )
        with client.acquire_external_writer_guard(receipt=active.receipt):
            client.write_lease_bytes(lease=active.lease, content=content)
        committed = client.commit_external_buffer(
            receipt=active.receipt,
            checksum=crc32_ieee(content),
            media_type="application/octet-stream",
        )
        with client.acquire_buffer_reader_guard(
            buffer_ref=committed.buffer_ref,
            deadline_ns=monotonic_ns() + 5_000_000_000,
        ):
            assert client.conditional_release(receipt=active.receipt) == "revoking"
            with pytest.raises(InvalidRequestError, match="pool 已满"):
                client.allocate_external_buffer(
                    size=1,
                    owner_kind="test",
                    owner_id="must-not-reuse",
                    deadline_ns=monotonic_ns() + 5_000_000_000,
                )
        summary = client.sweep_reclaiming_leases(pool_name="image")
        assert summary["released_count"] == 1
        client.close()
    finally:
        supervisor.stop()


def test_frame_reader_guard_prevents_ring_slot_overwrite(tmp_path: Path) -> None:
    """验证 FrameRef 复制期间 ring writer 不覆盖唯一槽位。"""

    settings = LocalBufferBrokerSettings(
        root_dir=str(tmp_path / "buffers"),
        default_pool_name="image",
        request_timeout_seconds=5.0,
        pools=(
            LocalBufferBrokerPoolSettings(
                pool_name="image",
                slot_size_bytes=4096,
                slot_count=1,
            ),
        ),
    )
    supervisor = LocalBufferBrokerProcessSupervisor(settings=settings)
    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None
        client.create_frame_channel(stream_id="camera-1", frame_capacity=1)
        first = client.write_frame(
            stream_id="camera-1",
            content=b"first-frame",
            media_type="application/octet-stream",
        )
        with client.acquire_frame_reader_guard(
            frame_ref=first,
            deadline_ns=monotonic_ns() + 5_000_000_000,
        ):
            assert bytes(client.read_frame_ref_view(first)) == b"first-frame"
            with pytest.raises(InvalidRequestError, match="reader 持有"):
                client.write_frame(
                    stream_id="camera-1",
                    content=b"must-not-overwrite",
                    media_type="application/octet-stream",
                )
        second = client.write_frame(
            stream_id="camera-1",
            content=b"second-frame",
            media_type="application/octet-stream",
        )
        assert bytes(client.read_frame_ref(second)) == b"second-frame"
        client.close()
    finally:
        supervisor.stop()


def _write_external(
    pool: MmapBufferPool,
    content: bytes,
    *,
    request_id: str,
):
    """写入并提交一份 external 测试数据。"""

    deadline_ns = monotonic_ns() + 5_000_000_000
    allocation = pool.allocate_external(
        size=len(content),
        owner_kind="workflow-trigger-write",
        owner_id=f"trigger-source-1:{request_id}",
        deadline_ns=deadline_ns,
    )
    with acquire_mmap_guard(
        guard_path=allocation.receipt.writer_guard_path,
        deadline_ns=deadline_ns,
        poll_interval_seconds=0.001,
    ):
        _write_lease_bytes(
            file_path=Path(allocation.lease.file_path),
            offset=allocation.lease.offset,
            content=content,
        )
    pool.commit_external_lease(
        receipt=allocation.receipt,
        checksum_algorithm=1,
        checksum=crc32_ieee(content),
        media_type="application/octet-stream",
    )
    return allocation


def _write_external_with_client(client, content: bytes, *, pool_name: str):
    """通过真实 broker client 写入并提交一份 external 数据。"""

    deadline_ns = monotonic_ns() + 5_000_000_000
    allocation = client.allocate_external_buffer(
        size=len(content),
        owner_kind="workflow-trigger-write",
        owner_id=f"trigger-source-process:{pool_name}",
        deadline_ns=deadline_ns,
        pool_name=pool_name,
    )
    with client.acquire_external_writer_guard(receipt=allocation.receipt):
        client.write_lease_bytes(lease=allocation.lease, content=content)
    client.commit_external_buffer(
        receipt=allocation.receipt,
        checksum=crc32_ieee(content),
        media_type="application/octet-stream",
    )
    return allocation


def _write_lease_bytes(*, file_path: Path, offset: int, content: bytes) -> None:
    """模拟独立 SDK 进程向精确 lease 区间写入。"""

    with file_path.open("r+b", buffering=0) as file_handle:
        view = mmap.mmap(file_handle.fileno(), 0, access=mmap.ACCESS_WRITE)
        try:
            view[offset : offset + len(content)] = content
        finally:
            view.close()


def _build_pool(
    tmp_path: Path,
    *,
    slot_count: int = 1,
    revocation_grace_seconds: float = 0.01,
) -> MmapBufferPool:
    """创建小容量且可观察状态迁移的测试 pool。"""

    slot_size_bytes = 4096
    return MmapBufferPool(
        MmapBufferPoolConfig(
            pool_name="image-test",
            root_dir=tmp_path / "buffers" / "image-test",
            file_size_bytes=slot_size_bytes * slot_count,
            slot_size_bytes=slot_size_bytes,
            file_name="image-test-001.dat",
            broker_epoch="epoch-stage2",
            reader_guard_slots=16,
            revocation_grace_seconds=revocation_grace_seconds,
        )
    )
