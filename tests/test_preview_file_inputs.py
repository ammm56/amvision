"""Preview 文件快照复用 pin 生命周期，内存计费不包含整文件副本。"""

from hashlib import sha256
from types import SimpleNamespace
import pytest

from backend.service.application.workflows.preview.buffers import (
    PreviewBuffers,
    PreviewMemoryError,
)
from backend.service.application.workflows.preview.inputs import PreviewInputStore
from backend.service.application.workflows.point_cloud.execution_policy import (
    PreviewFilePolicy,
)
from backend.service.infrastructure.filesystem.shared_temporary_input import (
    open_temporary_input,
)


def buffers(root, **kwargs):
    """显式测试磁盘预算，生产不采用这些数值。"""
    result = PreviewBuffers(
        session_limit=64,
        total_limit=128,
        file_root=root,
        file_policy=PreviewFilePolicy(session_bytes=1024, total_bytes=2048),
        **kwargs,
    )
    result.require_registered_owner = True
    result.register_owner("owner")
    return result


def test_cloud_capabilities_have_no_implicit_defaults(tmp_path):
    """能力接口不暴露内部策略，也不能跨项目读取；未配置明确为 null。"""
    from tests.test_workflow_runtime_invoke_api import _create_runtime_api_client
    from tests.api_test_support import build_bearer_headers, issue_test_user_token
    client, sessions, _ = _create_runtime_api_client(tmp_path, database_name="capability.db", enable_local_buffer_broker=False)
    try:
        with client:
            token = issue_test_user_token(sessions, username="cloud-reader",
                scopes=("workflows:read",), project_ids=("project-1",))
            headers = build_bearer_headers(token)
            root = "/api/v1/workflows/projects"
            response = client.get(f"{root}/project-1/measurement-resources/cloud/capabilities", headers=headers)
            assert response.status_code == 200
            assert response.json() == {"max_archive_bytes": None, "renderer": None}
            assert client.get(f"{root}/other/measurement-resources/cloud/capabilities", headers=headers).status_code == 403
    finally:
        sessions.engine.dispose()


def test_file_snapshot_kept_until_worker_returns_pin(tmp_path):
    memory = buffers(tmp_path)
    try:
        content = bytes(range(256)) * 2
        key = memory.allocate_file(
            "owner",
            len(content),
            media_type="application/octet-stream",
            file_name="cloud.ply",
        )
        memory.write_chunk("owner", key, 0, content)
        memory.commit("owner", key)
        descriptor = memory.pin_descriptor("owner", key)
        store = PreviewInputStore(
            SimpleNamespace(settings=None, root_dir=tmp_path), "p", "s"
        )
        ref = store.register_snapshot(descriptor)
        assert ref["checksum"] == sha256(content).hexdigest()
        assert memory.stats()["bytes"] == 0 and memory.stats()["file_bytes"] == len(
            content
        )
        memory.release_owner("owner")
        with store.open_read_snapshot(
            ref["object_key"], expected_checksum=ref["checksum"]
        ) as snapshot:
            assert snapshot.stream.read(4) == content[:4]
            snapshot.stream.seek(256)
            assert snapshot.stream.read() == content[256:]
        store.clear()
        memory.unpin("owner", key)
        assert memory.stats()["blocks"] == 0
        with pytest.raises((OSError, ValueError)):
            with open_temporary_input(descriptor["file_identity"]):
                pass
    finally:
        memory.close()
    assert not list(tmp_path.iterdir())


def test_file_admission_and_invalid_upload(tmp_path):
    memory = buffers(tmp_path)
    try:
        with pytest.raises(PreviewMemoryError, match="capacity"):
            memory.allocate_file("owner", 1025, media_type="a", file_name="a")
        key = memory.allocate_file("owner", 20, media_type="a", file_name="a")
        with pytest.raises(PreviewMemoryError, match="incomplete"):
            memory.commit("owner", key)
        with pytest.raises(PreviewMemoryError, match="chunk"):
            memory.write_chunk("owner", key, 1, b"a")
        with pytest.raises(PreviewMemoryError, match="length"):
            memory.write_chunk("owner", key, 0, b"x" * 21)
        memory.write_chunk("owner", key, 0, b"x" * 20)
        memory.commit("owner", key)
        with pytest.raises(PreviewMemoryError, match="already_committed"):
            memory.commit("owner", key)
        with pytest.raises(PreviewMemoryError, match="not_display"):
            with memory.borrow("owner", key):
                pass
        memory.expire_uploads(now=10**20)
        assert memory.stats()["file_bytes"] == 0
    finally:
        memory.close()


def test_unconfigured_policy_does_not_allocate_disk(tmp_path):
    memory = PreviewBuffers(file_root=tmp_path)
    memory.register_owner("owner")
    try:
        with pytest.raises(PreviewMemoryError, match="unconfigured"):
            memory.allocate_file("owner", 1, media_type="a", file_name="a")
        assert not list(tmp_path.iterdir())
    finally:
        memory.close()


def _file_owner_process(root, connection):
    """测试故障注入：不执行 Python finally，验证 OS 文件所有权。"""
    import os
    from backend.service.infrastructure.filesystem.shared_temporary_input import (
        SharedTemporaryInput,
    )

    file = SharedTemporaryInput(root)
    file.write(b"full-input")
    connection.send(file.seal())
    connection.recv()
    os._exit(0)


def test_owner_crash_keeps_active_reader_then_reclaims_file(tmp_path):
    """父 owner 突然退出时，已打开的 reader 可结束读取，最终无暂存残留。"""
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_file_owner_process, args=(tmp_path, child))
    process.start()
    child.close()
    try:
        assert parent.poll(15)
        identity = parent.recv()
        with open_temporary_input(identity) as reader:
            parent.send("exit")
            process.join(10)
            assert not process.is_alive()
            assert reader.read() == b"full-input"
        assert not list(tmp_path.iterdir())
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()
            process.join(10)
        process.close()


def test_upload_api_and_real_worker_share_only_snapshot(tmp_path):
    """HTTP 接收后真实 worker 读取文件引用，结束后输入配额与文件全部归还。"""
    from time import monotonic, sleep
    from uuid import uuid4
    from tests.api_test_support import (
        build_test_headers,
        build_bearer_headers,
        issue_test_user_token,
    )
    from tests.test_workflow_runtime_invoke_api import (
        _create_runtime_api_client,
        _build_file_metadata_application,
    )

    client, sessions, _ = _create_runtime_api_client(
        tmp_path, database_name="file-input.db", enable_local_buffer_broker=False
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            manager = client.app.state.workflow_preview_sessions
            manager.buffers.file_policy = PreviewFilePolicy(
                session_bytes=1000000, total_bytes=2000000
            )
            template, application = _build_file_metadata_application(multiple=False)
            created = client.post(
                "/api/v1/workflows/preview-sessions",
                headers=headers,
                json={
                    "project_id": "project-1",
                    "application_id": application.application_id,
                    "editor_session_id": "test",
                },
            )
            assert created.status_code == 201
            sid = created.json()["session_id"]
            url = f"/api/v1/workflows/preview-sessions/{sid}/inputs/file"
            params = {"byte_length": 600000, "file_name": "metadata.json"}
            headers = {**headers, "Content-Type": "application/json"}
            readonly = build_bearer_headers(
                issue_test_user_token(
                    sessions,
                    username="reader",
                    scopes=("workflows:read",),
                    project_ids=("project-1",),
                )
            )
            assert (
                client.post(
                    url, headers=readonly, params=params, content=b"x"
                ).status_code
                == 403
            )
            assert (
                client.post(
                    url, headers=headers, params=params, content=b"short"
                ).status_code
                == 413
            )
            assert manager.buffers.stats()["file_bytes"] == 0
            response = client.post(
                url,
                headers=headers,
                params=params,
                content=(b"x" * 100000 for _ in range(6)),
            )
            assert response.status_code == 201, response.text
            assert "path" not in response.text and "name" not in response.json()
            key = response.json()["input_id"]
            assert manager.buffers.stats()["bytes"] == 0
            with client.websocket_connect(
                f"/ws/v1/workflows/preview-sessions/{sid}", headers=headers
            ) as ws:
                ws.receive_json()
                accepted = client.post(
                    f"/api/v1/workflows/preview-sessions/{sid}/runs",
                    headers=headers,
                    json={
                        "request_id": str(uuid4()),
                        "document_revision": "r",
                        "input_ids": {"request_file": [key]},
                        "application": application.model_dump(mode="json"),
                        "template": template.model_dump(mode="json"),
                    },
                )
                assert accepted.status_code == 202, accepted.text
                deadline = monotonic() + 30
                while monotonic() < deadline:
                    session = manager._sessions[sid]
                    if (
                        session.run["state"] not in {"accepted", "running"}
                        and not manager.pool._active
                    ):
                        break
                    sleep(0.02)
                assert session.run["state"] == "succeeded", session.run
                assert (
                    session.run["outputs"]["metadata"]["value"]["content_length"]
                    == 600000
                )
                assert manager.buffers.stats()["file_bytes"] == 0
                assert manager.buffers.stats()["pins"] == 0
            client.delete(f"/api/v1/workflows/preview-sessions/{sid}", headers=headers)
    finally:
        sessions.engine.dispose()
