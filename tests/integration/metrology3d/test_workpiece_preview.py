"""完整工件在编辑器 Preview 中交付所有测量证据，不以发布 Runtime 替代。"""

import json
from contextlib import ExitStack
from pathlib import Path
import platform
from time import monotonic, sleep
from uuid import uuid4

import pytest

from scripts.metrology_workpiece import build_documents
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.representative_workflow import representative_policy


def test_complete_workpiece_editor_preview(tmp_path, request):
    """真实文件上传、正式图、独立 Preview worker、完整显示及会话释放。"""
    sample = request.config.getoption("--cloud-sample")
    if not sample:
        pytest.skip("通过 --cloud-sample 提供完整真实工件")
    sample = Path(sample)
    with published_system(tmp_path, point_cloud_policy=representative_policy()) as system:
        template, app = build_documents()
        system.publish(point_limit=500_000, documents=(template, app))
        root = "/preview-sessions"
        sid = system.call("POST", root, status=201, json=dict(
            project_id="project-1", application_id=app.application_id,
            editor_session_id="full-workpiece-preview",
        ))["session_id"]
        root += "/" + sid
        manager = system.client.app.state.workflow_preview_sessions
        connections = ExitStack()
        try:
            with sample.open("rb") as stream:
                response = system.client.post(system.base + root + "/inputs/file",
                    headers={**system.headers, "Content-Type": "application/octet-stream"},
                    params=dict(byte_length=sample.stat().st_size, file_name=sample.name),
                    content=stream)
            assert response.status_code == 201, response.text
            key = response.json()["input_id"]
            ws = connections.enter_context(system.client.websocket_connect(
                f"/ws/v1/workflows/preview-sessions/{sid}", headers=system.headers,
            ))
            assert ws.receive_json()["type"] == "session.snapshot"
            accepted = system.call("POST", root + "/runs", status=202, json=dict(
                request_id=str(uuid4()), document_revision="full-workpiece",
                input_ids={"cloud": [key]}, application=app.model_dump(mode="json"),
                template=template.model_dump(mode="json"),
            ))
            # 总验收窗口覆盖完整 ASCII 解码和 worker 冷启动，不改变生产节点超时。
            deadline = monotonic() + 240
            while monotonic() < deadline:
                with manager._lock:
                    session = manager._sessions[sid]
                    done = session.run["state"] not in {"accepted", "running"}
                if done and not manager.pool._active:
                    break
                sleep(0.05)
            assert session.run["state"] == "succeeded", session.run
            assert len(session.nodes) == 111
            assert all(node["status"] == "succeeded" for node in session.nodes.values())
            displays = [value["payload"] for value in session.displays.values()]
            cloud = next(value for value in displays if value["type"] == "point-cloud-preview")
            descriptor = cloud["value_descriptor"]
            assert descriptor["kind"] == "json", descriptor
            with manager.buffers.borrow(sid, descriptor["blob_id"]) as content:
                full = json.loads(bytes(content))
            assert full["state"] == "ready"
            assert full["display_point_count"] == 500_000
            assert len(full["measurements"]["items"]) == 50
            assert len([c for c in full["geometry"]["curves"] if c["kind"] == "circle"]) == 2
            assert manager.buffers.stats()["file_bytes"] == 0
            assert manager.buffers.stats()["pins"] == 0
            output = request.config.getoption("--cloud-report-dir")
            if output:
                path = Path(output)
                path.mkdir(parents=True, exist_ok=True)
                (path / f"preview-{platform.system().lower()}.json").write_text(json.dumps(dict(
                    run_id=accepted["run_id"], nodes=111, state="succeeded", measurements=50,
                    display_points=500_000, circles=2, full_evidence=True,
                ), indent=2), encoding="utf-8")
        finally:
            connections.close()
            system.call("DELETE", root, status=204)
        assert manager.buffers.stats() == dict(blocks=0, bytes=0, file_bytes=0, pins=0, reserved_bytes=0)
        system.assert_reclaimed()
