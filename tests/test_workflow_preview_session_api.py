"""Preview v1 REST/WS 协议、输入完整性和二进制 ACK 验证。"""

import hashlib
from uuid import uuid4, UUID
import pytest
from starlette.websockets import WebSocketDisconnect

from backend.contracts.workflows.preview_session import encode_preview_frame, decode_preview_frame, PREVIEW_CHUNK_SIZE
from tests.api_test_support import build_test_headers
from tests.test_workflow_runtime_invoke_api import _create_runtime_api_client


def test_websocket_upload_roundtrip_and_atomic_snapshot(tmp_path):
    """WS 输入不使用 multipart，返回相同字节；错误不能污染已提交输入。"""
    client, sessions, _ = _create_runtime_api_client(tmp_path, database_name="session-api.db", enable_local_buffer_broker=False)
    manager = client.app.state.workflow_preview_sessions
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            created = client.post("/api/v1/workflows/preview-sessions", headers=headers,
                                  json={"project_id": "project-1", "application_id": "app", "editor_session_id": "editor"})
            assert created.status_code == 201, created.text
            sid = created.json()["session_id"]
            other = manager.create(principal_id="another-owner", project_id="project-1", application_id="app", editor_session_id="other")["session_id"]
            with client.websocket_connect(f"/ws/v1/workflows/preview-sessions/{other}", headers=headers) as denied:
                with pytest.raises(WebSocketDisconnect) as error:
                    denied.receive_json()
                assert error.value.code == 4404
            assert client.post(f"/api/v1/workflows/preview-sessions/{other}/runs/run/cancel", headers=headers).status_code == 404
            manager.release(other, "another-owner")
            content = bytes(range(256)) * 2000
            transfer = uuid4()
            with client.websocket_connect(f"/ws/v1/workflows/preview-sessions/{sid}", headers=headers) as ws:
                assert ws.receive_json()["type"] == "session.snapshot"
                ws.send_json({"type": "input.begin", "transfer_id": str(transfer), "byte_length": len(content),
                              "media_type": "image/png", "sha256": hashlib.sha256(content).hexdigest()})
                assert ws.receive_json()["type"] == "input.ready"
                for index, offset in enumerate(range(0, len(content), PREVIEW_CHUNK_SIZE)):
                    ws.send_bytes(encode_preview_frame(transfer, index, content[offset:offset + PREVIEW_CHUNK_SIZE], kind=1))
                    assert ws.receive_json()["chunk_index"] == index
                ws.send_json({"type": "input.commit", "transfer_id": str(transfer)})
                committed = ws.receive_json()
                blob = committed["input_id"]
                assert "name" not in committed
                ws.send_json({"type": "display.get", "blob_id": blob})
                assert ws.receive_json()["type"] == "display.begin"
                received = bytearray()
                while len(received) < len(content):
                    identity, index, chunk = decode_preview_frame(ws.receive_bytes(), expected_kind=2)
                    assert identity == UUID(blob)
                    received.extend(chunk)
                    chunk.release()
                    ws.send_json({"type": "display.ack", "blob_id": blob, "chunk_index": index})
                assert ws.receive_json()["type"] == "display.end"
                assert received == content
                ws.send_bytes(encode_preview_frame(transfer, 0, b"late", kind=1))
                assert ws.receive_json()["type"] == "protocol.error"
            with client.websocket_connect(f"/ws/v1/workflows/preview-sessions/{sid}", headers=headers) as ws:
                assert ws.receive_json()["payload"]["watermark"] == 0
            assert client.delete(f"/api/v1/workflows/preview-sessions/{sid}", headers=headers).status_code == 204
            assert manager.buffers.stats() == {"blocks": 0, "bytes": 0, "pins": 0, "reserved_bytes": 0}
    finally:
        manager.close()
        sessions.engine.dispose()


@pytest.mark.parametrize("failure", ["digest", "incomplete", "chunk_order"])
def test_failed_upload_releases_memory_and_slot_without_disconnect(tmp_path, failure):
    """连续损坏上传立即释放；同一连接仍可提交完整输入，不能耗尽四个槽位。"""
    client, sessions, _ = _create_runtime_api_client(tmp_path, database_name="upload-failure.db", enable_local_buffer_broker=False)
    manager = client.app.state.workflow_preview_sessions
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    content = b"real-image-bytes"
    try:
        with client:
            response = client.post("/api/v1/workflows/preview-sessions", headers=headers,
                                   json={"project_id": "project-1", "application_id": "app", "editor_session_id": "editor"})
            assert response.status_code == 201
            sid = response.json()["session_id"]
            with client.websocket_connect(f"/ws/v1/workflows/preview-sessions/{sid}", headers=headers) as ws:
                assert ws.receive_json()["type"] == "session.snapshot"
                for attempt in range(6):
                    invalid = attempt < 5
                    transfer = uuid4()
                    ws.send_json({"type": "input.begin", "transfer_id": str(transfer), "byte_length": len(content),
                                  "media_type": "image/jpeg", "sha256": "0" * 64 if invalid and failure == "digest" else hashlib.sha256(content).hexdigest()})
                    assert ws.receive_json()["type"] == "input.ready"
                    chunk = content[:-1] if invalid and failure == "incomplete" else content
                    ws.send_bytes(encode_preview_frame(transfer, 1 if invalid and failure == "chunk_order" else 0, chunk, kind=1))
                    reply = ws.receive_json()
                    if not (invalid and failure == "chunk_order"):
                        assert reply["type"] == "input.ack"
                        ws.send_json({"type": "input.commit", "transfer_id": str(transfer)})
                        reply = ws.receive_json()
                    if invalid:
                        assert reply["type"] == "protocol.error"
                        expected = {"digest": "preview_input_digest_invalid", "incomplete": "preview_input_incomplete", "chunk_order": "preview_input_chunk_invalid"}
                        assert reply["error"] == expected[failure]
                        assert manager.buffers.stats() == {"blocks": 0, "bytes": 0, "pins": 0, "reserved_bytes": 0}
                    else:
                        assert reply["type"] == "input.committed"
                        with manager.buffers.borrow(sid, reply["input_id"]) as value:
                            assert bytes(value) == content
            assert client.delete(f"/api/v1/workflows/preview-sessions/{sid}", headers=headers).status_code == 204
            assert manager.buffers.stats() == {"blocks": 0, "bytes": 0, "pins": 0, "reserved_bytes": 0}
    finally:
        manager.close()
        sessions.engine.dispose()
