"""LocalBufferBroker 第 0 阶段规则与 mmap pool 测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep

import pytest

from backend.contracts.buffers import BufferLease, BufferRef, FrameRef
from backend.nodes.runtime_support import (
    IMAGE_TRANSPORT_BUFFER,
    IMAGE_TRANSPORT_FRAME,
    load_image_bytes,
    require_image_payload,
    resolve_image_reference,
)
from backend.service.application.deployments.published_inference_gateway import PublishedInferenceRequest
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.local_buffers import MmapBufferPool, MmapBufferPoolConfig


def test_buffer_ref_frame_ref_and_lease_contracts_are_json_stable() -> None:
    """验证 BufferRef、FrameRef 和 BufferLease 可以稳定序列化。"""

    created_at = datetime(2026, 5, 12, tzinfo=timezone.utc)
    lease = BufferLease(
        lease_id="lease-1",
        buffer_id="image-test:0",
        owner_kind="preview-run",
        owner_id="preview-1",
        pool_name="image-test",
        file_path="runtime/buffers/image-test/pool-001.dat",
        offset=0,
        size=6,
        created_at=created_at,
        state="writing",
        broker_epoch="epoch-1",
        generation=1,
    )
    buffer_ref = BufferRef(
        buffer_id=lease.buffer_id,
        lease_id=lease.lease_id,
        path=lease.file_path,
        offset=lease.offset,
        size=lease.size,
        shape=(2, 3, 1),
        dtype="uint8",
        layout="HWC",
        pixel_format="GRAY",
        media_type="image/raw",
        broker_epoch=lease.broker_epoch,
        generation=lease.generation,
    )
    frame_ref = FrameRef(
        stream_id="line-a-camera-1",
        sequence_id=1,
        buffer_id="ring-line-a-camera-1",
        path="runtime/buffers/image-test/pool-001.dat",
        offset=64,
        size=6,
        shape=(2, 3, 1),
        dtype="uint8",
        layout="HWC",
        pixel_format="GRAY",
        media_type="image/raw",
        broker_epoch="epoch-1",
        generation=1,
    )

    assert lease.model_dump(mode="json")["format_id"] == "amvision.buffer-lease.v1"
    assert buffer_ref.model_dump(mode="json")["shape"] == [2, 3, 1]
    assert frame_ref.model_dump(mode="json")["format_id"] == "amvision.frame-ref.v1"


def test_mmap_buffer_pool_ring_frames_overwrite_stale_frame_refs(tmp_path: Path) -> None:
    """验证 mmap pool 可以写入 ring frame，并拒绝被覆盖的旧 FrameRef。"""

    with _build_pool(tmp_path) as pool:
        channel = pool.create_frame_channel(stream_id="line-a-camera-1", frame_capacity=2)

        first_frame = pool.write_frame(
            stream_id="line-a-camera-1",
            content=b"frame-1",
            media_type="image/raw",
            shape=(1, 7, 1),
            dtype="uint8",
            layout="HWC",
            pixel_format="GRAY",
        )
        second_frame = pool.write_frame(
            stream_id="line-a-camera-1",
            content=b"frame-2",
            media_type="image/raw",
        )
        third_frame = pool.write_frame(
            stream_id="line-a-camera-1",
            content=b"frame-3",
            media_type="image/raw",
        )
        status = pool.build_status()

        assert channel["frame_capacity"] == 2
        assert first_frame.sequence_id == 0
        assert second_frame.sequence_id == 1
        assert third_frame.sequence_id == 2
        assert pool.read_frame_ref(second_frame) == b"frame-2"
        assert pool.read_frame_ref(third_frame) == b"frame-3"
        with pytest.raises(InvalidRequestError, match="覆盖|复用"):
            pool.read_frame_ref(first_frame)
        assert status["frame_active_count"] == 2
        assert status["frame_write_count"] == 3
        assert status["frame_overwrite_count"] == 1
        assert status["frame_channels"][0]["overwritten_frame_count"] == 1


def test_mmap_buffer_pool_writes_reads_and_rejects_stale_refs(tmp_path: Path) -> None:
    """验证最小 mmap pool 支持读写并拒绝已经释放或复用的旧引用。"""

    with _build_pool(tmp_path) as pool:
        first_result = pool.write_bytes(
            content=b"abcdef",
            owner_kind="preview-run",
            owner_id="preview-1",
            media_type="image/raw",
            shape=(2, 3, 1),
            dtype="uint8",
            layout="HWC",
            pixel_format="GRAY",
        )

        assert first_result.lease.state == "active"
        assert first_result.buffer_ref.generation == 1
        assert pool.read_buffer_ref(first_result.buffer_ref) == b"abcdef"

        second_slot_result = pool.write_bytes(
            content=b"ghij",
            owner_kind="preview-run",
            owner_id="preview-2",
            media_type="image/raw",
            shape=(2, 2, 1),
            dtype="uint8",
            layout="HWC",
            pixel_format="GRAY",
        )

        assert second_slot_result.buffer_ref.offset == 64
        assert pool.read_buffer_ref(second_slot_result.buffer_ref) == b"ghij"
        pool.release(second_slot_result.lease.lease_id)

        pool.release(first_result.lease.lease_id)
        with pytest.raises(InvalidRequestError, match="不可读"):
            pool.read_buffer_ref(first_result.buffer_ref)

        reused_slot_result = pool.write_bytes(
            content=b"xyz",
            owner_kind="preview-run",
            owner_id="preview-3",
            media_type="image/raw",
            shape=(1, 3, 1),
            dtype="uint8",
            layout="HWC",
            pixel_format="GRAY",
        )

        assert reused_slot_result.buffer_ref.generation == 2
        with pytest.raises(InvalidRequestError, match="复用"):
            pool.read_buffer_ref(first_result.buffer_ref)


def test_mmap_buffer_pool_expires_ttl_leases_and_reports_status(tmp_path: Path) -> None:
    """验证 mmap pool 会回收过期 lease 并更新状态指标。"""

    with _build_pool(tmp_path) as pool:
        write_result = pool.write_bytes(
            content=b"ttl-image",
            owner_kind="preview-run",
            owner_id="preview-ttl",
            media_type="image/raw",
            ttl_seconds=1.0,
        )

        assert pool.build_status()["active_count"] == 1
        expired_count = pool.expire_leases(now=datetime.now(timezone.utc) + timedelta(seconds=2.0))
        status = pool.build_status()

        assert expired_count == 1
        assert status["active_count"] == 0
        assert status["free_count"] == 2
        assert status["expired_count"] == 1
        with pytest.raises(InvalidRequestError, match="不可读"):
            pool.read_buffer_ref(write_result.buffer_ref)


def test_mmap_buffer_pool_reclaims_expired_lease_on_pool_full_then_retries_once(tmp_path: Path) -> None:
    """验证 pool 满时会先回收过期 lease，且成功重试不计入 pool_full。"""

    with _build_pool(tmp_path) as pool:
        pool.allocate(size=1, owner_kind="test", owner_id="expired", ttl_seconds=0.001)
        active_lease = pool.allocate(size=1, owner_kind="test", owner_id="active")
        sleep(0.01)

        recovered_lease = pool.allocate(size=1, owner_kind="test", owner_id="recovered")
        status = pool.build_status()

        assert recovered_lease.owner_id == "recovered"
        assert status["free_count"] == 0
        assert status["expired_count"] == 1
        assert status["pool_full_count"] == 0
        assert status["allocation_failure_count"] == 0
        pool.release(active_lease.lease_id)
        pool.release(recovered_lease.lease_id)


def test_mmap_buffer_pool_can_abort_and_destroy_frame_channel(tmp_path: Path) -> None:
    """验证 writing frame 可 abort，channel 可销毁且旧 FrameRef 会失效。"""

    with _build_pool(tmp_path) as pool:
        pool.create_frame_channel(stream_id="camera-a", frame_capacity=2)
        reservation = pool.allocate_frame(stream_id="camera-a", size=4)
        pool.abort_frame(reservation=reservation)
        assert pool.build_status()["frame_writing_count"] == 0

        frame_ref = pool.write_frame(
            stream_id="camera-a",
            content=b"data",
            media_type="image/raw",
        )
        assert pool.destroy_frame_channel(stream_id="camera-a") == 2
        status = pool.build_status()
        assert status["frame_reserved_count"] == 0
        assert status["free_count"] == 2
        assert status["frame_channel_count"] == 0
        assert status["frame_channel_created_count"] == 1
        assert status["frame_channel_destroy_count"] == 1
        assert status["frame_abort_count"] == 1
        with pytest.raises(InvalidRequestError):
            pool.read_frame_ref(frame_ref)


def test_mmap_buffer_pool_high_frequency_soak_keeps_capacity_stable(tmp_path: Path) -> None:
    """高频顺序写入释放不会造成 free_count 漂移或虚假 pool-full。"""

    iterations = 20_000
    with MmapBufferPool(
        MmapBufferPoolConfig(
            pool_name="soak",
            root_dir=tmp_path / "soak",
            file_size_bytes=4 * 64,
            slot_size_bytes=64,
            broker_epoch="epoch-soak",
        )
    ) as pool:
        for sequence_id in range(iterations):
            result = pool.write_bytes(
                content=sequence_id.to_bytes(8, "little"),
                owner_kind="soak-test",
                owner_id=f"frame-{sequence_id}",
                media_type="application/octet-stream",
            )
            pool.release(result.lease.lease_id)

        status = pool.build_status()
        assert status["free_count"] == 4
        assert status["pool_full_count"] == 0
        assert status["expired_count"] == 0
        assert status["allocation_count"] == iterations
        assert status["released_count"] == iterations


def test_resolve_image_reference_and_load_image_bytes_support_buffer_ref(tmp_path: Path) -> None:
    """验证 image-ref helper 可以通过 LocalBufferBroker reader 读取 BufferRef。"""

    with _build_pool(tmp_path) as pool:
        write_result = pool.write_bytes(
            content=b"raw-image",
            owner_kind="workflow-runtime",
            owner_id="run-1",
            media_type="image/raw",
            shape=(3, 3, 1),
            dtype="uint8",
            layout="HWC",
            pixel_format="GRAY",
        )
        image_payload = {
            "transport_kind": IMAGE_TRANSPORT_BUFFER,
            "buffer_ref": write_result.buffer_ref.model_dump(mode="json"),
        }
        request = _build_request(payload=image_payload, local_buffer_reader=pool)

        normalized_payload = require_image_payload(image_payload)
        resolved_image = resolve_image_reference(request)
        loaded_payload, loaded_bytes = load_image_bytes(request)
        inference_request = PublishedInferenceRequest(
            task_type="detection",
            deployment_instance_id="deployment-1",
            image_payload=normalized_payload,
            trace_id="trace-1",
        )

        assert normalized_payload["transport_kind"] == IMAGE_TRANSPORT_BUFFER
        assert normalized_payload["media_type"] == "image/raw"
        assert normalized_payload["width"] == 3
        assert normalized_payload["height"] == 3
        assert normalized_payload["shape"] == [3, 3, 1]
        assert normalized_payload["dtype"] == "uint8"
        assert normalized_payload["layout"] == "HWC"
        assert normalized_payload["pixel_format"] == "gray8"
        assert resolved_image.buffer_ref == write_result.buffer_ref
        assert resolved_image.shape == (3, 3, 1)
        assert resolved_image.pixel_format == "gray8"
        assert loaded_payload["buffer_ref"]["lease_id"] == write_result.lease.lease_id
        assert loaded_bytes == b"raw-image"
        assert inference_request.image_payload["transport_kind"] == IMAGE_TRANSPORT_BUFFER


def test_resolve_image_reference_and_load_image_bytes_support_frame_ref(tmp_path: Path) -> None:
    """验证 image-ref helper 可以通过 LocalBufferBroker reader 读取 FrameRef。"""

    with _build_pool(tmp_path) as pool:
        pool.create_frame_channel(stream_id="line-a-camera-1", frame_capacity=2)
        frame_ref = pool.write_frame(
            stream_id="line-a-camera-1",
            content=b"frame-image",
            media_type="image/raw",
            shape=(1, 11, 1),
            dtype="uint8",
            layout="HWC",
            pixel_format="GRAY",
        )
        image_payload = {
            "transport_kind": IMAGE_TRANSPORT_FRAME,
            "frame_ref": frame_ref.model_dump(mode="json"),
        }
        request = _build_request(payload=image_payload, local_buffer_reader=pool)

        normalized_payload = require_image_payload(image_payload)
        resolved_image = resolve_image_reference(request)
        loaded_payload, loaded_bytes = load_image_bytes(request)

        assert normalized_payload["transport_kind"] == IMAGE_TRANSPORT_FRAME
        assert normalized_payload["media_type"] == "image/raw"
        assert normalized_payload["width"] == 11
        assert normalized_payload["height"] == 1
        assert normalized_payload["shape"] == [1, 11, 1]
        assert normalized_payload["dtype"] == "uint8"
        assert normalized_payload["layout"] == "HWC"
        assert normalized_payload["pixel_format"] == "gray8"
        assert resolved_image.frame_ref == frame_ref
        assert resolved_image.shape == (1, 11, 1)
        assert resolved_image.pixel_format == "gray8"
        assert loaded_payload["frame_ref"]["sequence_id"] == 0
        assert loaded_bytes == b"frame-image"


def test_load_image_bytes_requires_local_buffer_reader_for_buffer_ref(tmp_path: Path) -> None:
    """验证 BufferRef 读取必须显式注入 LocalBufferBroker reader。"""

    with _build_pool(tmp_path) as pool:
        write_result = pool.write_bytes(
            content=b"raw-image",
            owner_kind="workflow-runtime",
            owner_id="run-1",
            media_type="image/raw",
        )
        request = _build_request(
            payload={
                "transport_kind": IMAGE_TRANSPORT_BUFFER,
                "buffer_ref": write_result.buffer_ref.model_dump(mode="json"),
            },
            local_buffer_reader=None,
        )

        with pytest.raises(ServiceConfigurationError, match="LocalBufferBroker reader"):
            load_image_bytes(request)


@pytest.mark.parametrize("slot_count", (16, 8, 4))
def test_mmap_buffer_pool_uses_configured_low_memory_slot_count(tmp_path: Path, slot_count: int) -> None:
    """验证 mmap pool 按 16、8、4 个槽位分配，并在容量耗尽时稳定返回错误。"""

    with MmapBufferPool(
        MmapBufferPoolConfig(
            pool_name=f"image-test-{slot_count}",
            root_dir=tmp_path / f"buffers-{slot_count}",
            file_size_bytes=64 * slot_count,
            slot_size_bytes=64,
            broker_epoch="epoch-test",
        )
    ) as pool:
        leases = [
            pool.allocate(size=1, owner_kind="test", owner_id=f"owner-{index}")
            for index in range(slot_count)
        ]

        status = pool.build_status()
        assert pool.slot_count == slot_count
        assert status["used_count"] == slot_count
        assert status["free_count"] == 0
        assert leases[-1].offset == (slot_count - 1) * 64
        with pytest.raises(InvalidRequestError, match="pool 已满"):
            pool.allocate(size=1, owner_kind="test", owner_id="overflow")

        for lease in leases:
            pool.release(lease.lease_id)
        assert pool.build_status()["free_count"] == slot_count


def _build_pool(tmp_path: Path) -> MmapBufferPool:
    """构造测试用 mmap pool。"""

    return MmapBufferPool(
        MmapBufferPoolConfig(
            pool_name="image-test",
            root_dir=tmp_path / "buffers",
            file_size_bytes=128,
            slot_size_bytes=64,
            broker_epoch="epoch-test",
        )
    )


def _build_request(
    *,
    payload: dict[str, object],
    local_buffer_reader: object | None,
) -> WorkflowNodeExecutionRequest:
    """构造 runtime_support 测试使用的最小节点请求。"""

    execution_metadata: dict[str, object] = {"workflow_run_id": "local-buffer-test"}
    if local_buffer_reader is not None:
        execution_metadata["local_buffer_reader"] = local_buffer_reader
    return WorkflowNodeExecutionRequest(
        node_id="test-node",
        node_definition=object(),
        input_values={"image": payload},
        execution_metadata=execution_metadata,
    )
