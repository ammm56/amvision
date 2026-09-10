"""完整值分页与资源回收测试，不需要模型或浏览器长时间运行。"""

import hashlib
import json
from multiprocessing.shared_memory import SharedMemory

import pytest

from backend.service.application.workflows.preview.buffers import PreviewBuffers, PreviewMemoryError
from backend.service.application.workflows.preview.values import PreviewValues


class Bridge:
    """直接调用同一所有者接口的测试适配，不替代跨进程集成测试。"""

    def __init__(self, buffers):
        self.buffers = buffers

    def reserve(self, key, size):
        self.buffers.reserve("session", key, size)

    def publish(self, content, media_type):
        identity = self.buffers.allocate("session", len(content), media_type=media_type)
        descriptor = self.buffers.writer_descriptor("session", identity)
        memory = SharedMemory(name=descriptor["name"])
        try:
            memory.buf[:len(content)] = content
        finally:
            memory.close()
        return self.buffers.publish_writer("session", identity)


def test_roi_values_preserve_execution_image_ids_as_diagnostic_json():
    """ROI 完整值不因包含图像 id 丢失；id 只作诊断，不能作为显示 Blob 读取。"""
    from contextlib import closing
    value = {"rois": [{"bbox_xyxy": [0, 1, 10, 20], "enabled": False}],
             "source_image": {"transport_kind": "memory", "image_handle": "opaque-registry-id"}}
    with closing(PreviewBuffers()) as buffers:
        descriptor = PreviewValues(Bridge(buffers)).describe(value)
        assert descriptor == {"kind": "inline", "value": value, "reference_scope": "execution"}
        assert buffers.stats()["blocks"] == 0


def test_large_nested_value_transfers_completely_without_truncating_false_or_zero():
    buffers = PreviewBuffers()
    values = PreviewValues(Bridge(buffers))
    try:
        for value in [0, False, None, ""]:
            assert values.describe(value) == {"kind": "inline", "value": value}
        source = {"items": [{"index": index, "value": False} for index in range(2000)]}
        descriptor = values.describe(source)
        assert descriptor["kind"] == "json"
        with buffers.borrow("session", descriptor["blob_id"]) as content:
            assert json.loads(bytes(content)) == source
        assert buffers.stats()["reserved_bytes"] == 0
    finally:
        buffers.close()
    assert buffers.stats() == {"blocks": 0, "bytes": 0, "pins": 0, "reserved_bytes": 0}


def test_unused_committed_input_expires_but_published_display_does_not():
    buffers = PreviewBuffers()
    try:
        upload = buffers.allocate("session", 4, media_type="text/plain", digest=hashlib.sha256(b"test").hexdigest())
        buffers.write_chunk("session", upload, 0, b"test")
        buffers.commit("session", upload)
        published = Bridge(buffers).publish(b"test", "text/plain")["blob_id"]
        buffers.expire_uploads(now=float("inf"))
        assert buffers.live_ids("session") == {published}
        buffers.require_registered_owner = True
        buffers.register_owner("session")
        buffers.release_owner("session")
        with pytest.raises(PreviewMemoryError):
            buffers.allocate("session", 1, media_type="text/plain")
    finally:
        buffers.close()
