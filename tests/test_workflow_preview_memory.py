"""Preview 内存交接和二进制协议的真实生命周期测试。"""

import hashlib
import multiprocessing
from multiprocessing.shared_memory import SharedMemory
from uuid import uuid4

import pytest

from backend.contracts.workflows.preview_session import decode_preview_frame, encode_preview_frame
from backend.service.application.workflows.preview.buffers import PreviewBuffers, PreviewMemoryError


def _read_child(descriptor, sender):
    """spawn 子进程只附加父进程对象，不依赖路径或文件。"""
    memory = SharedMemory(name=descriptor["name"])
    try:
        sender.send(bytes(memory.buf[:descriptor["byte_length"]]))
    finally:
        memory.close()
        sender.close()


@pytest.fixture
def buffers():
    """测试失败也释放所有已分配的资源。"""
    store = PreviewBuffers(session_limit=16, total_limit=32)
    yield store
    store.close()


def test_upload_is_not_visible_until_complete_and_owner_is_checked(buffers):
    """未完成、跨会话、摘要不一致均不能成为执行输入。"""
    identity = buffers.allocate("a", 4, media_type="image/png", digest=hashlib.sha256(b"abcd").hexdigest())
    with pytest.raises(PreviewMemoryError):
        buffers.pin_descriptor("a", identity)
    with pytest.raises(PreviewMemoryError):
        buffers.write_chunk("b", identity, 0, b"abcd")
    buffers.write_chunk("a", identity, 0, b"ab")
    with pytest.raises(PreviewMemoryError):
        buffers.commit("a", identity)
    with pytest.raises(PreviewMemoryError):
        buffers.write_chunk("a", identity, 0, b"cd")
    buffers.write_chunk("a", identity, 1, b"cd")
    assert buffers.commit("a", identity)["byte_length"] == 4
    with buffers.borrow("a", identity) as view:
        assert bytes(view) == b"abcd"
        assert view.readonly
        buffers.release_owner("a")
        assert buffers.stats()["bytes"] == 4
        with pytest.raises(PreviewMemoryError):
            buffers.pin_descriptor("a", identity)
    assert buffers.stats() == {"blocks": 0, "bytes": 0, "pins": 0, "reserved_bytes": 0}


def test_budget_and_expired_upload_are_bounded(buffers):
    """每会话和全局限制均在分配前生效，超限不登记资源。"""
    buffers.allocate("a", 16, media_type="image/png")
    with pytest.raises(PreviewMemoryError, match="capacity"):
        buffers.allocate("a", 1, media_type="image/png")
    buffers.allocate("b", 16, media_type="image/png")
    with pytest.raises(PreviewMemoryError, match="capacity"):
        buffers.allocate("c", 1, media_type="image/png")
    assert buffers.stats()["bytes"] == 32
    buffers.expire_uploads(now=float("inf"))
    assert buffers.stats()["blocks"] == 0


def test_bad_digest_is_not_published(buffers):
    """错误内容不改变 ready 状态。"""
    identity = buffers.allocate("a", 4, media_type="image/png", digest="0" * 64)
    buffers.write_chunk("a", identity, 0, b"abcd")
    with pytest.raises(PreviewMemoryError, match="digest"):
        buffers.commit("a", identity)
    with pytest.raises(PreviewMemoryError):
        buffers.pin_descriptor("a", identity)


def test_real_spawn_reads_memory_while_owner_releases(buffers):
    """父进程请求释放后，已借用的子进程仍可读取，归还后映射不可再打开。"""
    identity = buffers.allocate("a", 4, media_type="image/png")
    buffers.write_chunk("a", identity, 0, b"abcd")
    buffers.commit("a", identity)
    descriptor = buffers.pin_descriptor("a", identity)
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=_read_child, args=(descriptor, writer))
    try:
        process.start()
        writer.close()
        buffers.release_owner("a")
        assert reader.poll(15)
        assert reader.recv() == b"abcd"
        process.join(10)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        reader.close()
        writer.close()
        process.close()
        buffers.unpin("a", identity)
    assert buffers.stats()["bytes"] == 0
    with pytest.raises(FileNotFoundError):
        SharedMemory(name=descriptor["name"])


def test_binary_frame_roundtrip_and_invalid_messages():
    """帧头长度固定、跨方向或截断消息不能进入上传缓存。"""
    identity = uuid4()
    frame = encode_preview_frame(identity, 3, b"abcd", kind=1)
    assert len(frame) == 36
    result_id, index, content = decode_preview_frame(frame, expected_kind=1)
    assert (result_id, index, bytes(content)) == (identity, 3, b"abcd")
    for damaged in (frame[:5], frame[:-1], frame + b"a", b"xxxx" + frame[4:]):
        with pytest.raises(ValueError):
            decode_preview_frame(damaged, expected_kind=1)
    with pytest.raises(ValueError):
        decode_preview_frame(frame, expected_kind=2)
