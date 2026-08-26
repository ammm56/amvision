"""LocalBuffer 固定 arena 公开契约与图片运行时接入门禁。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.contracts.buffers import BufferLease, BufferRef, FrameRef
from backend.nodes.runtime_support import (
    IMAGE_TRANSPORT_BUFFER,
    IMAGE_TRANSPORT_FRAME,
    load_image_bytes,
    require_image_payload,
    resolve_image_reference,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.local_buffers.local_buffer_arena_pool import (
    LocalBufferArenaPool,
)
from backend.service.infrastructure.local_buffers.mmap_buffer_arena import (
    MmapBufferArenaConfig,
)


_MIB = 1024 * 1024


def test_buffer_ref_frame_ref_and_lease_contracts_are_json_stable() -> None:
    """公开契约只包含 arena locator，不暴露文件系统路径。"""

    created_at = datetime(2026, 5, 12, tzinfo=timezone.utc)
    common = {
        "buffer_id": "local-buffer-main:0",
        "arena_id": "local-buffer-main",
        "descriptor_index": 0,
        "descriptor_generation": 2,
        "broker_epoch": "1" * 32,
        "offset": 0,
        "content_length": 6,
        "allocation_capacity_bytes": _MIB,
    }
    lease = BufferLease(
        lease_id="lease-1",
        owner_kind="preview-run",
        owner_id="preview-1",
        created_at=created_at,
        state="writing",
        **common,
    )
    buffer_ref = BufferRef(
        lease_id=lease.lease_id,
        shape=(2, 3, 1),
        dtype="uint8",
        layout="HWC",
        pixel_format="GRAY8",
        media_type="image/raw",
        **common,
    )
    frame_ref = FrameRef(
        stream_id="line-a-camera-1",
        sequence_id=1,
        shape=(2, 3, 1),
        dtype="uint8",
        layout="HWC",
        pixel_format="GRAY8",
        media_type="image/raw",
        **common,
    )

    assert lease.model_dump(mode="json")["format_id"] == "amvision.buffer-lease.v1"
    assert buffer_ref.model_dump(mode="json")["shape"] == [2, 3, 1]
    assert frame_ref.model_dump(mode="json")["format_id"] == "amvision.frame-ref.v1"
    assert "path" not in buffer_ref.model_dump()
    assert "pool_name" not in frame_ref.model_dump()


def test_released_buffer_ref_cannot_read_reused_extent(tmp_path: Path) -> None:
    """generation fencing 阻止旧 BufferRef 读取重新分配的同一地址。"""

    pool = _pool(tmp_path)
    try:
        first = _write(pool, b"first")
        pool.release(first.lease.lease_id)
        second = _write(pool, b"second")

        assert first.buffer_ref.offset == second.buffer_ref.offset
        assert first.buffer_ref.descriptor_generation != second.buffer_ref.descriptor_generation
        with pytest.raises(InvalidRequestError):
            pool.read_buffer_ref(first.buffer_ref)
        assert pool.read_buffer_ref(second.buffer_ref) == b"second"
    finally:
        pool.close()


def test_runtime_image_helpers_accept_buffer_and_frame_refs(tmp_path: Path) -> None:
    """Workflow 图片 helper 可直接消费固定 arena 的 BufferRef 与 FrameRef。"""

    pool = _pool(tmp_path)
    try:
        result = _write(
            pool,
            b"raw-image",
            shape=(3, 3, 1),
            pixel_format="GRAY8",
        )
        buffer_payload = {
            "transport_kind": IMAGE_TRANSPORT_BUFFER,
            "buffer_ref": result.buffer_ref.model_dump(mode="json"),
        }
        buffer_request = _request(buffer_payload, pool)
        resolved = resolve_image_reference(buffer_request)
        _, content = load_image_bytes(buffer_request)
        assert resolved.buffer_ref == result.buffer_ref
        assert content == b"raw-image"

        pool.create_frame_channel(
            stream_id="camera-1",
            frame_count=2,
            max_frame_content_length=32,
        )
        reservation = pool.allocate_frame(stream_id="camera-1", content_length=5)
        pool.write_frame_bytes(reservation=reservation, content=memoryview(b"frame"))
        frame = pool.commit_frame(
            reservation=reservation,
            media_type="image/raw",
            shape=(1, 5, 1),
            dtype="uint8",
            layout="HWC",
            pixel_format="GRAY8",
        )
        frame_payload = {
            "transport_kind": IMAGE_TRANSPORT_FRAME,
            "frame_ref": frame.model_dump(mode="json"),
        }
        frame_request = _request(frame_payload, pool)
        _, frame_content = load_image_bytes(frame_request)
        assert require_image_payload(frame_payload)["width"] == 5
        assert frame_content == b"frame"
    finally:
        pool.close()


def test_buffer_ref_requires_explicit_local_buffer_reader(tmp_path: Path) -> None:
    """BufferRef 不允许退回磁盘或其他隐藏传输路径。"""

    pool = _pool(tmp_path)
    try:
        result = _write(pool, b"raw-image")
        request = _request(
            {
                "transport_kind": IMAGE_TRANSPORT_BUFFER,
                "buffer_ref": result.buffer_ref.model_dump(mode="json"),
            },
            None,
        )
        with pytest.raises(ServiceConfigurationError, match="LocalBufferBroker reader"):
            load_image_bytes(request)
    finally:
        pool.close()


def _pool(tmp_path: Path) -> LocalBufferArenaPool:
    return LocalBufferArenaPool(
        MmapBufferArenaConfig(
            root_dir=tmp_path / "buffers",
            arena_id="local-buffer-main",
            arena_size_bytes=16 * _MIB,
            min_block_size_bytes=_MIB,
            max_allocation_bytes=8 * _MIB,
            reader_guard_slots=4,
            revocation_grace_seconds=0.05,
        )
    )


def _write(
    pool: LocalBufferArenaPool,
    content: bytes,
    *,
    shape: tuple[int, ...] = (),
    pixel_format: str | None = None,
):
    lease = pool.allocate(
        content_length=len(content),
        owner_kind="workflow-runtime",
        owner_id="run-1",
    )
    pool.write_lease_bytes(lease=lease, content=memoryview(content))
    return pool.commit_lease(
        lease=lease,
        media_type="image/raw",
        shape=shape,
        dtype="uint8" if shape else None,
        layout="HWC" if shape else None,
        pixel_format=pixel_format,
    )


def _request(
    payload: dict[str, object],
    reader: object | None,
) -> WorkflowNodeExecutionRequest:
    metadata: dict[str, object] = {"workflow_run_id": "run-1"}
    if reader is not None:
        metadata["local_buffer_reader"] = reader
    return WorkflowNodeExecutionRequest(
        node_id="test-node",
        node_definition=object(),
        input_values={"image": payload},
        execution_metadata=metadata,
    )
