"""LocalBuffer 单 arena 高层 lease、External 与 frame channel 门禁。"""

from __future__ import annotations

from time import monotonic_ns

import pytest

from backend.service.application.errors import (
    InvalidRequestError,
    LocalBufferCapacityError,
)
from backend.service.infrastructure.ipc.mmap_primitives import crc32_ieee
from backend.service.infrastructure.local_buffers.local_buffer_arena_pool import (
    LocalBufferArenaPool,
)
from backend.service.infrastructure.local_buffers.mmap_buffer_arena import (
    LocalBufferArenaError,
    MmapBufferArenaExternalAccess,
    MmapBufferArenaConfig,
)


_MIB = 1024 * 1024


def _pool(tmp_path) -> LocalBufferArenaPool:
    """构造测试用单 arena pool。"""

    return LocalBufferArenaPool(
        MmapBufferArenaConfig(
            root_dir=tmp_path,
            arena_id="local-buffer-main",
            arena_size_bytes=16 * _MIB,
            min_block_size_bytes=_MIB,
            max_allocation_bytes=8 * _MIB,
            reader_guard_slots=4,
            revocation_grace_seconds=0.05,
        )
    )


def _deadline() -> int:
    return monotonic_ns() + 5_000_000_000


def test_ordinary_lease_uses_dynamic_extent_and_buffer_ref_has_no_path(tmp_path) -> None:
    """普通写入按 content length 分配，公开引用不携带 mmap 路径。"""

    pool = _pool(tmp_path)
    try:
        payload = memoryview(b"encoded-image")
        lease = pool.allocate(
            content_length=payload.nbytes,
            owner_kind="workflow-runtime",
            owner_id="run-1",
        )
        pool.write_lease_bytes(lease=lease, content=payload)
        result = pool.commit_lease(lease=lease, media_type="image/png")

        assert result.lease.allocation_capacity_bytes == _MIB
        assert result.buffer_ref.content_length == payload.nbytes
        assert "path" not in result.buffer_ref.model_dump()
        assert "pool_name" not in result.buffer_ref.model_dump()
        assert pool.read_buffer_ref(result.buffer_ref) == payload
        pool.release(result.lease.lease_id)
        assert pool.build_status()["free_capacity_bytes"] == 16 * _MIB
    finally:
        pool.close()


def test_external_writer_receipt_crc_and_owner_handoff(tmp_path) -> None:
    """External writer 以私有 receipt 校验、发布并转移 owner。"""

    pool = _pool(tmp_path)
    try:
        payload = b"raw-bgr24"
        allocation = pool.allocate_external(
            content_length=len(payload),
            owner_kind="workflow-trigger-write",
            owner_id="request-1",
            deadline_ns=_deadline(),
        )
        with pool.arena.acquire_writer_view(
            pool._require_record(allocation.lease.lease_id).low_receipt
        ) as view:
            view[:] = payload
        committed = pool.commit_external_lease(
            receipt=allocation.receipt,
            checksum=crc32_ieee(payload),
            media_type="image/raw",
            shape=(1, 3, 3),
            dtype="uint8",
            layout="HWC",
            pixel_format="BGR24",
        )
        current_receipt = pool._build_receipt(
            pool._require_record(committed.lease.lease_id)
        )
        transferred = pool.transfer_ownership_batch(
            receipts=(current_receipt,),
            new_owner_kind="workflow-runtime",
            new_owner_id="run-1",
            deadline_ns=_deadline(),
        )[0]

        assert transferred.owner_kind == "workflow-runtime"
        assert transferred.owner_token != current_receipt.owner_token
        assert pool.conditional_release(receipt=current_receipt) == "stale"
        assert pool.conditional_release(receipt=transferred) == "released"
    finally:
        pool.close()


def test_reserved_output_can_publish_shorter_content_and_reclaim(tmp_path) -> None:
    """预留大 extent 后按实际长度发布，不破坏 allocator identity 与回收。"""

    pool = _pool(tmp_path)
    try:
        payload = memoryview(b"short-result")
        lease = pool.allocate(
            content_length=_MIB,
            owner_kind="inference-daemon",
            owner_id="request-1",
        )
        pool.write_lease_bytes(lease=lease, content=payload)
        result = pool.commit_lease(
            lease=lease,
            media_type="image/png",
            content_length=payload.nbytes,
        )

        assert result.buffer_ref.content_length == payload.nbytes
        assert result.buffer_ref.allocation_capacity_bytes == _MIB
        assert pool.read_buffer_ref(result.buffer_ref) == payload
        pool.release(result.lease.lease_id)
        assert pool.build_status()["free_capacity_bytes"] == 16 * _MIB
    finally:
        pool.close()


def test_external_checksum_failure_keeps_writing_lease_recoverable(tmp_path) -> None:
    """CRC 错误不发布 ACTIVE，调用方可按原 receipt 安全回收。"""

    pool = _pool(tmp_path)
    try:
        allocation = pool.allocate_external(
            content_length=4,
            owner_kind="workflow-trigger-write",
            owner_id="request-1",
            deadline_ns=_deadline(),
        )
        record = pool._require_record(allocation.lease.lease_id)
        with pool.arena.acquire_writer_view(record.low_receipt) as view:
            view[:] = b"data"
        with pytest.raises(InvalidRequestError, match="checksum"):
            pool.commit_external_lease(
                receipt=allocation.receipt,
                checksum=0,
                media_type="image/raw",
            )
        assert pool.conditional_release(receipt=allocation.receipt) == "released"
    finally:
        pool.close()


def test_frame_channel_ring_wrap_rejects_old_sequence_and_destroys_all(tmp_path) -> None:
    """frame extent 长期复用，ring wrap 后旧 FrameRef 失效。"""

    pool = _pool(tmp_path)
    try:
        channel = pool.create_frame_channel(
            stream_id="camera-1",
            frame_count=2,
            max_frame_content_length=32,
        )
        assert channel["frame_count"] == 2
        refs = []
        for payload in (b"frame-0", b"frame-1", b"frame-2"):
            reservation = pool.allocate_frame(
                stream_id="camera-1",
                content_length=len(payload),
            )
            pool.write_frame_bytes(
                reservation=reservation,
                content=memoryview(payload),
            )
            refs.append(
                pool.commit_frame(
                    reservation=reservation,
                    media_type="image/raw",
                )
            )

        with pytest.raises(InvalidRequestError, match="覆盖"):
            pool.validate_frame_ref(refs[0])
        assert pool.read_frame_ref(refs[2]) == b"frame-2"
        assert pool.destroy_frame_channel(stream_id="camera-1") == 2
        assert pool.build_status()["frame_reserved_capacity_bytes"] == 0
    finally:
        pool.close()


def test_frame_generation_fences_external_reader_before_ring_overwrite(tmp_path) -> None:
    """下一次 frame reservation 先提升 generation，外部旧引用不能读到新帧。"""

    pool = _pool(tmp_path)
    external = MmapBufferArenaExternalAccess(pool.config)
    try:
        pool.create_frame_channel(
            stream_id="camera-1",
            frame_count=1,
            max_frame_content_length=32,
        )
        first_reservation = pool.allocate_frame(
            stream_id="camera-1",
            content_length=5,
        )
        pool.write_frame_bytes(
            reservation=first_reservation,
            content=memoryview(b"first"),
        )
        first = pool.commit_frame(
            reservation=first_reservation,
            media_type="image/raw",
        )
        with external.acquire_reader_view(first) as view:
            assert bytes(view) == b"first"

        second_reservation = pool.allocate_frame(
            stream_id="camera-1",
            content_length=6,
        )
        with pytest.raises(LocalBufferArenaError, match="identity"):
            with external.acquire_reader_view(first):
                pass
        pool.write_frame_bytes(
            reservation=second_reservation,
            content=memoryview(b"second"),
        )
        second = pool.commit_frame(
            reservation=second_reservation,
            media_type="image/raw",
        )
        with external.acquire_reader_view(second) as view:
            assert bytes(view) == b"second"
    finally:
        external.close()
        pool.close()


def test_batch_transfer_validation_failure_changes_no_owner(tmp_path) -> None:
    """foreign/stale receipt 使整批 handoff 失败且不修改合法 lease。"""

    pool = _pool(tmp_path)
    try:
        allocations = [
            pool.allocate_external(
                content_length=4,
                owner_kind="workflow-runtime",
                owner_id="run-1",
                deadline_ns=_deadline(),
            )
            for _index in range(2)
        ]
        stale = allocations[1].receipt.model_copy(update={"owner_token": "f" * 32})
        with pytest.raises(InvalidRequestError):
            pool.transfer_ownership_batch(
                receipts=(allocations[0].receipt, stale),
                new_owner_kind="workflow-trigger-response",
                new_owner_id="request-1",
                deadline_ns=_deadline(),
            )
        pool.validate_ownership_batch(
            receipts=(allocations[0].receipt, allocations[1].receipt),
            expected_states={"writing"},
        )
        for allocation in allocations:
            assert pool.conditional_release(receipt=allocation.receipt) == "released"
    finally:
        pool.close()


def test_arena_capacity_failures_keep_stable_service_error_codes(tmp_path) -> None:
    """总容量与外部碎片满载立即失败，不被误报成服务配置错误。"""

    pool = _pool(tmp_path)
    try:
        leases = [
            pool.allocate(
                content_length=4 * _MIB,
                owner_kind="workflow-runtime",
                owner_id=f"run-{index}",
            )
            for index in range(4)
        ]
        pool.release(leases[0].lease_id)
        pool.release(leases[2].lease_id)

        with pytest.raises(LocalBufferCapacityError) as fragmented:
            pool.allocate(
                content_length=8 * _MIB,
                owner_kind="workflow-runtime",
                owner_id="fragmented",
            )
        assert fragmented.value.code == (
            "local_buffer_contiguous_capacity_exhausted"
        )
        assert fragmented.value.details["failure_kind"] == "contiguous_capacity"

        pool.allocate(
            content_length=4 * _MIB,
            owner_kind="workflow-runtime",
            owner_id="consume-free-root",
        )
        with pytest.raises(LocalBufferCapacityError) as exhausted:
            pool.allocate(
                content_length=5 * _MIB,
                owner_kind="workflow-runtime",
                owner_id="exhausted",
            )
        assert exhausted.value.code == "local_buffer_capacity_exhausted"
        assert exhausted.value.details["failure_kind"] == "total_capacity"
    finally:
        pool.close()
