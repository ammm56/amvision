"""完整值分页与资源回收测试，不需要模型或浏览器长时间运行。"""

import hashlib
import json
from multiprocessing.shared_memory import SharedMemory

import pytest

from backend.service.application.workflows.preview.buffers import (
    PreviewBuffers,
    PreviewMemoryError,
)
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
            memory.buf[: len(content)] = content
        finally:
            memory.close()
        return self.buffers.publish_writer("session", identity)


def test_roi_values_preserve_execution_image_ids_as_diagnostic_json():
    """ROI 完整值不因包含图像 id 丢失；id 只作诊断，不能作为显示 Blob 读取。"""
    from contextlib import closing

    value = {
        "rois": [{"bbox_xyxy": [0, 1, 10, 20], "enabled": False}],
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "opaque-registry-id",
        },
    }
    with closing(PreviewBuffers()) as buffers:
        descriptor = PreviewValues(Bridge(buffers)).describe(value)
        assert descriptor == {
            "kind": "inline",
            "value": value,
            "reference_scope": "execution",
        }
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
    assert buffers.stats() == {
        "blocks": 0,
        "bytes": 0,
        "file_bytes": 0,
        "pins": 0,
        "reserved_bytes": 0,
    }


def test_unused_committed_input_expires_but_published_display_does_not():
    buffers = PreviewBuffers()
    try:
        upload = buffers.allocate(
            "session",
            4,
            media_type="text/plain",
            digest=hashlib.sha256(b"test").hexdigest(),
        )
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


def test_cloud_display_uses_existing_blob_channel_and_releases_reservations():
    """二进制显示不能塞进控制事件；节点原始业务值保持不变。"""
    from types import SimpleNamespace
    from backend.service.application.workflows.preview.display import (
        PreviewDisplayCapture,
    )

    buffers = PreviewBuffers()
    events = []
    capture = PreviewDisplayCapture(
        Bridge(buffers), lambda kind, data: events.append((kind, data))
    )
    body = {
        "type": "point-cloud-preview",
        "format_id": "amvision.point-cloud-preview.v1",
        "state": "ready",
        "display_point_count": 60_000,
        "data": {"content": "A" * 32000},
        "geometry": {
            "planes": [
                {"samples": {"classes": [1] * 60_000, "residuals": [0.01] * 60_000}}
            ]
        },
    }
    try:
        capture.capture(
            node_id="cloud",
            definition=SimpleNamespace(
                node_type_id="custom.metrology3d.cloud-preview",
                output_ports=[SimpleNamespace(name="body")],
            ),
            outputs={"body": body},
            invocation_id="once",
            duration_ms=1,
        )
        capture.close()
        display = next(
            data["payload"] for kind, data in events if kind == "display.updated"
        )
        assert display["data"] is None and display["paged"] is True
        assert "geometry" not in display
        assert len(json.dumps(display)) < 4096
        descriptor = display["value_descriptor"]
        with buffers.borrow("session", descriptor["blob_id"]) as view:
            assert json.loads(bytes(view)) == body
        assert body["data"]["content"] == "A" * 32000
        assert buffers.stats()["reserved_bytes"] == 0
    finally:
        capture.close()
        buffers.close()


def test_cloud_sample_allowance_does_not_relax_metadata_or_byte_limits():
    """完整三维平面标量可以传输；嵌套/伪造数组和超预算仍拒绝。"""
    from contextlib import closing
    from backend.service.application.workflows.runtime_preview import (
        RuntimePreviewCapture,
        MAX_PREVIEW_BYTES,
    )
    from types import SimpleNamespace

    body = {
        "type": "point-cloud-preview",
        "format_id": "amvision.point-cloud-preview.v1",
        "state": "ready",
        "display_point_count": 60_000,
        "data": {"content": "A" * 32000},
        "geometry": {
            "planes": [
                {"samples": {"classes": [1] * 60_000, "residuals": [0.01] * 60_000}}
            ]
        },
    }
    definition = SimpleNamespace(
        capability_tags=("ui.preview",),
        node_type_id="custom.metrology3d.cloud-preview",
        output_ports=[SimpleNamespace(name="body")],
    )
    capture = RuntimePreviewCapture()
    capture.capture(
        node_id="cloud",
        definition=definition,
        outputs={"body": body},
        invocation_id="one",
        duration_ms=1,
    )
    assert capture.error is None and 0 < capture.budget[1] <= 100_000
    assert capture.budget[0] < MAX_PREVIEW_BYTES
    with closing(PreviewBuffers()) as buffers:
        values = PreviewValues(Bridge(buffers))
        assert values.describe({"items": [0] * 100_000})["kind"] == "unavailable"
        assert (
            values.describe({**body, "metadata": [0] * 100_000})["kind"]
            == "unavailable"
        )
        body["geometry"]["planes"][0]["samples"]["residuals"][0] = []
        assert values.describe(body)["kind"] == "unavailable"
        body["geometry"]["planes"][0]["samples"]["residuals"][0] = 0.01
        assert (
            values.describe({**body, "data": {"content": "A" * MAX_PREVIEW_BYTES}})[
                "kind"
            ]
            == "unavailable"
        )
        assert buffers.stats()["reserved_bytes"] == 0
