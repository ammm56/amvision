"""Preview 已握手连接必须以 WebSocket 关闭码拒绝失效身份。"""

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.api_test_support import issue_test_user_token
from tests.test_workflow_runtime_invoke_api import _create_runtime_api_client


@pytest.mark.parametrize(
    "identity,code",
    [("missing", 4401), ("invalid", 4401), ("revoked", 4401), ("scope", 4403)],
)
def test_preview_rejects_identity_before_subscription(
    tmp_path, monkeypatch, identity, code
):
    """拒绝发生在订阅及资源分配之前，不发送 HTTP 响应或泄漏会话存在性。"""
    client, sessions, _ = _create_runtime_api_client(
        tmp_path, database_name="preview-auth.db", enable_local_buffer_broker=False
    )
    manager = client.app.state.workflow_preview_sessions

    def forbidden(*args, **kwargs):
        raise AssertionError("Unauthorized request reached preview manager")

    monkeypatch.setattr(manager, "authorize", forbidden)
    try:
        with client:
            token = "invalid-test-token"
            headers = {}
            if identity == "revoked":
                login = client.post(
                    "/api/v1/auth/login",
                    json={"username": "amvar", "password": "123456"},
                )
                assert login.status_code == 200, login.text
                token = login.json()["access_token"]
                assert (
                    client.post(
                        "/api/v1/auth/logout",
                        headers={"Authorization": "Bearer " + token},
                    ).status_code
                    == 204
                )
            if identity == "scope":
                restricted = issue_test_user_token(
                    sessions,
                    username="limited",
                    scopes=("datasets:read",),
                    project_ids=("project-1",),
                )
                headers = {"Authorization": "Bearer " + restricted}
            suffix = (
                "?access_token=" + token if identity in ("invalid", "revoked") else ""
            )
            with client.websocket_connect(
                "/ws/v1/workflows/preview-sessions/not-owned" + suffix, headers=headers
            ) as ws:
                with pytest.raises(WebSocketDisconnect) as error:
                    ws.receive_json()
                assert error.value.code == code
            assert manager.buffers.stats() == {
                "blocks": 0,
                "bytes": 0,
                "file_bytes": 0,
                "pins": 0,
                "reserved_bytes": 0,
            }
    finally:
        manager.close()
        sessions.engine.dispose()
