"""LocalBufferBroker 固定 arena 进程、控制面与 Workflow cleanup 门禁。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic_ns

import pytest

from backend.service.application.local_buffers import (
    LocalBufferBrokerProcessSupervisor,
    LocalBufferBrokerSettings,
)
from backend.service.application.errors import LocalBufferCapacityError
from backend.service.application.workflows.execution_cleanup import (
    register_local_buffer_lease_cleanup,
)
from backend.service.application.workflows.worker.manager import (
    WorkflowRuntimeWorkerManager,
)


_MIB = 1024 * 1024


def test_broker_rejects_noncanonical_main_arena_id() -> None:
    """后端主 arena identity 必须与所有 SDK 固定为同一个 v1 值。"""

    with pytest.raises(ValueError, match="必须固定为 local-buffer-main"):
        LocalBufferBrokerSettings(arena_id="custom-main")


def test_broker_process_serves_dynamic_extents_and_capacity_metrics(
    tmp_path: Path,
) -> None:
    """独立 Broker 按内容分配最小 extent，并暴露 arena 守恒指标。"""

    supervisor = _supervisor(tmp_path)
    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None
        result = client.write_bytes(
            content=b"abcdef",
            owner_kind="preview-run",
            owner_id="preview-1",
            media_type="image/raw",
            shape=(2, 3, 1),
            dtype="uint8",
            layout="HWC",
            pixel_format="GRAY8",
        )
        status = client.get_status()

        assert status["state"] == "healthy"
        assert status["arena_id"] == "local-buffer-main"
        assert result.lease.allocation_capacity_bytes == _MIB
        assert client.read_buffer_ref(result.buffer_ref) == b"abcdef"
        client.release(result.lease.lease_id)
        assert client.get_status()["free_capacity_bytes"] == 16 * _MIB
    finally:
        supervisor.stop()

    assert supervisor.is_running is False


def test_shared_client_serializes_control_responses(tmp_path: Path) -> None:
    """多线程复用同一 client 时控制响应不会串包。"""

    supervisor = _supervisor(tmp_path)
    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None

        def read_status() -> tuple[str, ...]:
            return tuple(str(client.get_status()["state"]) for _ in range(20))

        with ThreadPoolExecutor(max_workers=3) as executor:
            results = tuple(executor.map(lambda _index: read_status(), range(3)))
        assert all(states == ("healthy",) * 20 for states in results)
    finally:
        supervisor.stop()


def test_transient_clients_unregister_router_channels(tmp_path: Path) -> None:
    """短生命周期同进程 client 关闭后不得泄漏 router channel。"""

    supervisor = _supervisor(tmp_path)
    supervisor.start()
    try:
        for _index in range(20):
            assert supervisor.get_status()["state"] == "healthy"
        health = supervisor.get_health_summary()
        router = health["router"]
        assert router["active_client_channel_count"] == 0
        assert router["pending_response_route_count"] == 0
        assert router["closed_channel_count"] >= 21
    finally:
        supervisor.stop()


def test_broker_client_preserves_capacity_error_and_failure_metrics(
    tmp_path: Path,
) -> None:
    """跨进程控制面保留满载错误码及 allocator 分类计数。"""

    supervisor = _supervisor(tmp_path)
    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None
        for index in range(2):
            client.allocate_buffer(
                content_length=8 * _MIB,
                owner_kind="test",
                owner_id=f"request-{index}",
            )
        with pytest.raises(LocalBufferCapacityError) as caught:
            client.allocate_buffer(
                content_length=1,
                owner_kind="test",
                owner_id="request-overflow",
            )
        assert caught.value.code == "local_buffer_capacity_exhausted"
        status = client.get_status()
        assert status["allocation_failure_counts"]["total_capacity"] == 1
    finally:
        supervisor.stop()


def test_external_writer_commit_handoff_and_fenced_release(tmp_path: Path) -> None:
    """External 写入、CRC、owner CAS 与旧 receipt fencing 形成完整闭环。"""

    supervisor = _supervisor(tmp_path)
    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None
        content = b"external-image"
        allocation = client.allocate_external_buffer(
            content_length=len(content),
            owner_kind="workflow-trigger-write",
            owner_id="request-1",
            deadline_ns=monotonic_ns() + 5_000_000_000,
        )
        client.write_lease_bytes(lease=allocation.lease, content=content)
        committed = client.publish_and_transfer_external_buffer(
            receipt=allocation.receipt,
            media_type="image/raw",
            new_owner_kind="workflow-runtime",
            new_owner_id="run-1",
            deadline_ns=monotonic_ns() + 5_000_000_000,
        )

        assert client.read_buffer_ref(committed.buffer_ref) == content
        assert client.conditional_release(receipt=allocation.receipt) == "stale"
        assert client.conditional_release(receipt=committed.receipt) == "released"
    finally:
        supervisor.stop()


def test_frame_channel_reuses_extents_without_stale_frame_access(
    tmp_path: Path,
) -> None:
    """Broker frame channel 原地复用 extent，ring wrap 后旧引用失效。"""

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
        first = client.write_frame(
            stream_id="camera-1",
            content=b"first",
            media_type="image/raw",
        )
        second = client.write_frame(
            stream_id="camera-1",
            content=b"second",
            media_type="image/raw",
        )

        assert first.descriptor_generation != second.descriptor_generation
        assert client.read_frame_ref(second) == b"second"
        assert client.destroy_frame_channel(stream_id="camera-1") == 1
    finally:
        supervisor.stop()


def test_workflow_parent_cleanup_releases_registered_lease(tmp_path: Path) -> None:
    """Worker 异常退出时父进程可按 lease id 幂等兜底回收。"""

    supervisor = _supervisor(tmp_path)
    supervisor.start()
    try:
        result = supervisor.write_bytes(
            content=b"cleanup",
            owner_kind="workflow-runtime",
            owner_id="run-1",
            media_type="image/raw",
        )
        metadata: dict[str, object] = {}
        register_local_buffer_lease_cleanup(
            metadata,
            lease_id=result.lease.lease_id,
        )
        manager = object.__new__(WorkflowRuntimeWorkerManager)
        manager.local_buffer_broker_event_channel_provider = (
            supervisor.get_event_channel
        )

        assert manager.cleanup_parent_local_buffer_leases(metadata) == 1
        assert manager.cleanup_parent_local_buffer_leases(metadata) == 0
        assert supervisor.get_status()["free_capacity_bytes"] == 16 * _MIB
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
            request_timeout_seconds=5.0,
            revocation_grace_seconds=0.05,
        )
    )
