"""真实 HTTP 流式上传和 Preview worker；禁止 TestClient 合并整文件请求体。"""

import json
import socket
from threading import Thread
from uuid import uuid4

import httpx
import uvicorn

from tests.integration.metrology3d.capacity_support import (
    read_options,
    report,
    settings,
    stage,
    write_ply,
)
from tests.integration.metrology3d.published_support import published_system, wait_for
from tests.metrology3d_transport_support import cloud_documents


def test_capacity_http_preview(tmp_path, request):
    """沿浏览器相同文件路由上传，未替换 loader、read-cloud 或 Preview handler。"""
    configuration = settings()
    size = request.config.getoption("--cloud-capacity-bytes")
    path = tmp_path / "input.ply"
    count = write_ply(path, size)
    with (
        report(request, "http") as evidence,
        published_system(
            tmp_path / "system",
            point_cloud_policy=configuration.workflow_runtime.point_cloud,
            broker_policy=configuration.local_buffer_broker,
        ) as system,
    ):
        template, app = cloud_documents(read_options().model_dump(mode="json"))
        system.publish(documents=(template, app))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                system.client.app, lifespan="off", log_level="error", access_log=False
            )
        )
        thread = Thread(
            target=lambda: server.run(sockets=[sock]),
            name="capacity-http",
            daemon=False,
        )
        thread.start()
        sid = None
        try:
            wait_for(lambda: server.started, timeout=30)
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}",
                headers=system.headers,
                timeout=180,
                trust_env=False,
            ) as http:
                base = "/api/v1/workflows/preview-sessions"
                created = http.post(
                    base,
                    json=dict(
                        project_id="project-1",
                        application_id=app.application_id,
                        editor_session_id="capacity",
                    ),
                )
                assert created.status_code == 201, created.text
                assert created.json()["file_upload_limit_bytes"] == 1000000000
                sid = created.json()["session_id"]
                url = f"{base}/{sid}/inputs/file"
                rejected = http.post(
                    url,
                    params=dict(byte_length=1000000001, file_name="large.ply"),
                    content=b"x",
                )
                assert rejected.status_code == 422, rejected.text
                assert rejected.json()["error"]["code"] == "request_validation_failed"
                manager = system.client.app.state.workflow_preview_sessions
                assert manager.buffers.stats()["file_bytes"] == 0
                with system.client.websocket_connect(
                    f"/ws/v1/workflows/preview-sessions/{sid}", headers=system.headers
                ) as ws:
                    ws.receive_json()
                    with (
                        stage(evidence, "incomplete_upload"),
                        path.open("rb") as stream,
                    ):

                        def truncated_body():
                            """实际发送接近上限的正文，只缺最后一字节。"""
                            remaining = size - 1
                            while remaining:
                                block = stream.read(min(262144, remaining))
                                assert block
                                remaining -= len(block)
                                yield block

                        incomplete = http.post(
                            url,
                            params=dict(byte_length=size, file_name="incomplete.ply"),
                            content=truncated_body(),
                        )
                        assert incomplete.status_code == 413, incomplete.text
                        assert manager.buffers.stats()["file_bytes"] == 0
                    with stage(evidence, "disconnected_upload"):
                        # 真正关闭仍有正文未发送的 TCP 连接，不用异常替换路由。
                        with socket.create_connection(("127.0.0.1", port), 10) as peer:
                            headers = {
                                **system.headers,
                                "Host": f"127.0.0.1:{port}",
                                "Content-Type": "application/octet-stream",
                                "Content-Length": str(size),
                                "Connection": "close",
                            }
                            head = (
                                f"POST {url}?byte_length={size}&file_name=aborted.ply HTTP/1.1\r\n"
                                + "".join(
                                    f"{key}: {value}\r\n"
                                    for key, value in headers.items()
                                )
                                + "\r\n"
                            )
                            peer.sendall(head.encode("ascii"))
                            with path.open("rb") as stream:
                                peer.sendall(stream.read(min(size // 2, 16777216)))
                            wait_for(
                                lambda: manager.buffers.stats()["file_bytes"] > 0,
                                timeout=10,
                            )
                        wait_for(
                            lambda: manager.buffers.stats()["file_bytes"] == 0,
                            timeout=10,
                        )
                        assert manager.buffers.stats()["pins"] == 0
                    evidence["incomplete_and_disconnected_reclaimed"] = True
                    evidence["truncated_body_bytes"] = size - 1
                    evidence["disconnected_body_bytes"] = min(size // 2, 16777216)
                    with stage(evidence, "http_upload"), path.open("rb") as stream:
                        uploaded = http.post(
                            url,
                            params=dict(byte_length=size, file_name="input.ply"),
                            content=iter(lambda: stream.read(262144), b""),
                            headers={"Content-Type": "application/octet-stream"},
                        )
                    assert uploaded.status_code == 201, uploaded.text
                    assert manager.buffers.stats()["bytes"] == 0
                    with stage(evidence, "preview_worker"):
                        accepted = http.post(
                            f"{base}/{sid}/runs",
                            json=dict(
                                request_id=str(uuid4()),
                                document_revision="capacity",
                                application=app.model_dump(mode="json"),
                                template=template.model_dump(mode="json"),
                                input_ids={"cloud": [uploaded.json()["input_id"]]},
                            ),
                        )
                        assert accepted.status_code == 202, accepted.text
                        wait_for(
                            lambda: (
                                manager._sessions[sid].run.get("state")
                                not in {"accepted", "running"}
                                and not manager.pool._active
                            ),
                            timeout=180,
                        )
                        run = manager._sessions[sid].run
                        assert run["state"] == "succeeded", run
                        display = run["outputs"]["preview_value"]
                        with manager.buffers.borrow(sid, display["blob_id"]) as view:
                            body = json.loads(bytes(view))["body"]
                        assert body["source_point_count"] == count
                        assert body["display_point_count"] == 1000
                        assert (
                            manager.buffers.stats()["file_bytes"]
                            == manager.buffers.stats()["pins"]
                            == 0
                        )
                    evidence["point_count"] = count
                    evidence["file_bytes_after_run"] = 0
                    evidence["pins_after_run"] = 0
                assert http.delete(f"{base}/{sid}").status_code == 204
                sid = None
                assert manager.buffers.stats()["blocks"] == 0
        finally:
            if sid is not None:
                system.client.delete(
                    f"/api/v1/workflows/preview-sessions/{sid}", headers=system.headers
                )
            server.should_exit = True
            thread.join(20)
            sock.close()
            assert not thread.is_alive()
