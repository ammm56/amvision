"""LocalBuffer External lease、reader guard 与批量 handoff 进程门禁。"""

from __future__ import annotations

from pathlib import Path
from time import monotonic_ns

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.local_buffers import (
    LocalBufferBrokerProcessSupervisor,
    LocalBufferBrokerSettings,
)


_MIB = 1024 * 1024


def test_active_reader_guard_blocks_reclaim_until_reader_exits(tmp_path: Path) -> None:
    """ACTIVE reader 存在时 lease 只能进入 REVOKING，不能被复用。"""

    supervisor = _supervisor(tmp_path)
    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None
        content = b"reader-owned"
        allocation = client.allocate_external_buffer(
            content_length=len(content),
            owner_kind="workflow-trigger-write",
            owner_id="request-1",
            deadline_ns=monotonic_ns() + 5_000_000_000,
        )
        client.write_lease_bytes(lease=allocation.lease, content=content)
        result = client.publish_and_transfer_external_buffer(
            receipt=allocation.receipt,
            media_type="image/raw",
            new_owner_kind="workflow-runtime",
            new_owner_id="run-1",
            deadline_ns=monotonic_ns() + 5_000_000_000,
        )
        with client.acquire_buffer_reader_guard(
            buffer_ref=result.buffer_ref,
            deadline_ns=monotonic_ns() + 5_000_000_000,
        ):
            assert client.conditional_release(receipt=result.receipt) == "revoking"
            assert client.get_status()["revoking_capacity_bytes"] == _MIB

        summary = client.sweep_reclaiming_leases()
        assert summary["released_count"] == 1
        assert client.get_status()["free_capacity_bytes"] == 16 * _MIB
    finally:
        supervisor.stop()


def test_batch_handoff_is_atomic_when_one_receipt_is_stale(tmp_path: Path) -> None:
    """任一 receipt 失效时整批 owner transfer 不产生部分提交。"""

    supervisor = _supervisor(tmp_path)
    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None
        allocations = tuple(
            client.allocate_external_buffer(
                content_length=4,
                owner_kind="workflow-trigger-write",
                owner_id=f"request-{index}",
                deadline_ns=monotonic_ns() + 5_000_000_000,
            )
            for index in range(2)
        )
        stale = allocations[1].receipt.model_copy(update={"owner_token": "f" * 32})
        with pytest.raises(InvalidRequestError):
            client.transfer_lease_ownership(
                receipts=(allocations[0].receipt, stale),
                new_owner_kind="workflow-runtime",
                new_owner_id="run-1",
                deadline_ns=monotonic_ns() + 5_000_000_000,
            )

        assert client.conditional_release(receipt=allocations[0].receipt) == "released"
        assert client.conditional_release(receipt=allocations[1].receipt) == "released"
    finally:
        supervisor.stop()


def test_frame_reader_guard_prevents_ring_overwrite(tmp_path: Path) -> None:
    """frame reader 未退出时同一 extent 的下一次 reservation 立即失败。"""

    supervisor = _supervisor(tmp_path)
    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None
        client.create_frame_channel(
            stream_id="camera-1",
            frame_count=1,
            max_frame_content_length=32,
        )
        frame = client.write_frame(
            stream_id="camera-1",
            content=b"first",
            media_type="image/raw",
        )
        with client.acquire_frame_reader_guard(
            frame_ref=frame,
            deadline_ns=monotonic_ns() + 5_000_000_000,
        ):
            with pytest.raises(InvalidRequestError, match="reader"):
                client.allocate_frame(stream_id="camera-1", content_length=6)

        second = client.write_frame(
            stream_id="camera-1",
            content=b"second",
            media_type="image/raw",
        )
        assert client.read_frame_ref(second) == b"second"
    finally:
        supervisor.stop()


def _supervisor(tmp_path: Path) -> LocalBufferBrokerProcessSupervisor:
    return LocalBufferBrokerProcessSupervisor(
        settings=LocalBufferBrokerSettings(
            root_dir=str(tmp_path / "buffers"),
            arena_size_bytes=16 * _MIB,
            min_block_size_bytes=_MIB,
            max_allocation_bytes=8 * _MIB,
            reader_guard_slots=4,
            startup_timeout_seconds=10.0,
            revocation_grace_seconds=0.05,
        )
    )
