"""本地用户、登录会话与长期调用 token API 测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.api.app import create_app
from backend.service.application.auth.default_local_auth_seeder import DEFAULT_LOCAL_AUTH_TOKEN
from backend.service.application.auth.local_auth_service import LocalAuthService, LocalAuthUserCreateRequest
from backend.service.settings import (
    BackendServiceAuthConfig,
    BackendServiceLocalAuthConfig,
    BackendServiceAuthProviderConfig,
    BackendServiceSettings,
    BackendServiceTaskManagerConfig,
)
from tests.api_test_support import build_bearer_headers, create_test_runtime


def test_local_auth_bootstrap_refresh_logout_and_system_me_resolves_session(tmp_path: Path) -> None:
    """验证 bootstrap、refresh、logout 与 system/me 的会话 token 语义。"""

    client, session_factory = _create_local_auth_test_client(
        tmp_path,
        database_name="local-auth-bootstrap-refresh.db",
    )

    try:
        with client:
            bootstrap_response = client.post(
                "/api/v1/auth/bootstrap-admin",
                json={
                    "username": "admin",
                    "password": "Admin12345",
                    "display_name": "Local Admin",
                },
            )
            bootstrap_payload = bootstrap_response.json()
            access_token = bootstrap_payload["access_token"]
            refresh_token = bootstrap_payload["refresh_token"]
            me_response = client.get(
                "/api/v1/system/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            second_bootstrap_response = client.post(
                "/api/v1/auth/bootstrap-admin",
                json={
                    "username": "admin-2",
                    "password": "Admin22345",
                    "display_name": "Local Admin 2",
                },
            )
            refresh_response = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )
            refresh_payload = refresh_response.json()
            refreshed_access_token = refresh_payload["access_token"]
            me_with_old_session_response = client.get(
                "/api/v1/system/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            me_with_refreshed_session_response = client.get(
                "/api/v1/system/me",
                headers={"Authorization": f"Bearer {refreshed_access_token}"},
            )
            logout_response = client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {refreshed_access_token}"},
            )
            me_after_logout_response = client.get(
                "/api/v1/system/me",
                headers={"Authorization": f"Bearer {refreshed_access_token}"},
            )
    finally:
        session_factory.engine.dispose()

    assert bootstrap_response.status_code == 201
    assert bootstrap_payload["token_type"] == "bearer"
    assert bootstrap_payload["user"]["username"] == "admin"
    assert bootstrap_payload["user"]["display_name"] == "Local Admin"
    assert bootstrap_payload["user"]["scopes"] == ["*"]
    assert bootstrap_payload["session_id"].startswith("session-")
    assert isinstance(bootstrap_payload["refresh_token"], str)
    assert bootstrap_payload["refresh_expires_at"] is not None

    assert me_response.status_code == 200
    me_payload = me_response.json()
    assert me_payload["principal_id"] == bootstrap_payload["user"]["user_id"]
    assert me_payload["username"] == "admin"
    assert me_payload["display_name"] == "Local Admin"
    assert me_payload["auth_source"] == "bearer-token"
    assert me_payload["auth_provider_kind"] == "local"
    assert me_payload["auth_credential_kind"] == "session"
    assert me_payload["auth_credential_id"] == bootstrap_payload["session_id"]
    assert me_payload["auth_session_id"] == bootstrap_payload["session_id"]
    assert me_payload["auth_token_id"] is None

    assert second_bootstrap_response.status_code == 400
    assert second_bootstrap_response.json()["error"]["code"] == "invalid_request"

    assert refresh_response.status_code == 200
    assert refresh_payload["session_id"] != bootstrap_payload["session_id"]
    assert refresh_payload["access_token"] != bootstrap_payload["access_token"]
    assert refresh_payload["refresh_token"] != bootstrap_payload["refresh_token"]

    assert me_with_old_session_response.status_code == 401
    assert me_with_old_session_response.json()["error"]["code"] == "authentication_required"

    assert me_with_refreshed_session_response.status_code == 200
    assert me_with_refreshed_session_response.json()["auth_credential_kind"] == "session"
    assert me_with_refreshed_session_response.json()["auth_credential_id"] == refresh_payload["session_id"]

    assert logout_response.status_code == 204
    assert me_after_logout_response.status_code == 401
    assert me_after_logout_response.json()["error"]["code"] == "authentication_required"


def test_local_auth_default_user_token_can_access_rest_and_websocket(tmp_path: Path) -> None:
    """验证新建用户默认长期 token 可访问 REST 与 WebSocket，并且不能走 logout。"""

    client, session_factory = _create_local_auth_test_client(
        tmp_path,
        database_name="local-auth-user-token-access.db",
    )

    try:
        with client:
            bootstrap_response = client.post(
                "/api/v1/auth/bootstrap-admin",
                json={
                    "username": "admin",
                    "password": "Admin12345",
                    "display_name": "Local Admin",
                },
            )
            admin_token = bootstrap_response.json()["access_token"]
            admin_headers = {"Authorization": f"Bearer {admin_token}"}
            create_user_response = client.post(
                "/api/v1/auth/users",
                headers=admin_headers,
                json={
                    "username": "viewer",
                    "password": "Viewer12345",
                    "display_name": "Workflow Viewer",
                    "project_ids": ["project-1"],
                    "scopes": ["workflows:read", "models:read"],
                },
            )
            create_user_payload = create_user_response.json()
            viewer_token = create_user_payload["initial_user_token"]["token"]
            viewer_user_id = create_user_payload["user"]["user_id"]
            viewer_me_response = client.get(
                "/api/v1/system/me",
                headers={"Authorization": f"Bearer {viewer_token}"},
            )
            logout_response = client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {viewer_token}"},
            )
            list_tokens_response = client.get(
                f"/api/v1/auth/users/{viewer_user_id}/tokens",
                headers=admin_headers,
            )
            with client.websocket_connect(
                f"/ws/v1/projects/events?project_id=project-1&access_token={viewer_token}"
            ) as websocket:
                connected_message = websocket.receive_json()
                snapshot_message = websocket.receive_json()
    finally:
        session_factory.engine.dispose()

    assert bootstrap_response.status_code == 201
    assert create_user_response.status_code == 201
    assert create_user_payload["user"]["username"] == "viewer"
    assert create_user_payload["user"]["project_ids"] == ["project-1"]
    assert create_user_payload["user"]["scopes"] == ["workflows:read", "models:read"]
    assert create_user_payload["initial_user_token"]["token_name"] == "default"
    assert create_user_payload["initial_user_token"]["expires_at"] is None

    assert viewer_me_response.status_code == 200
    viewer_me_payload = viewer_me_response.json()
    assert viewer_me_payload["project_ids"] == ["project-1"]
    assert viewer_me_payload["scopes"] == ["workflows:read", "models:read"]
    assert viewer_me_payload["auth_credential_kind"] == "user-token"
    assert viewer_me_payload["auth_token_name"] == "default"
    assert viewer_me_payload["auth_session_id"] is None

    assert logout_response.status_code == 400
    assert logout_response.json()["error"]["code"] == "invalid_request"

    assert list_tokens_response.status_code == 200
    assert [item["token_name"] for item in list_tokens_response.json()] == ["default"]

    assert connected_message["event_type"] == "projects.connected"
    assert snapshot_message["event_type"] == "projects.summary.snapshot"
    assert snapshot_message["resource_id"] == "project-1"


def test_auth_providers_endpoint_lists_local_and_configured_online_provider(tmp_path: Path) -> None:
    """验证账号 provider 目录会公开 local 和已配置的在线 provider。"""

    client, session_factory = _create_local_auth_test_client(
        tmp_path,
        database_name="auth-provider-catalog.db",
        auth_config=BackendServiceAuthConfig(
            mode="local",
            websocket_query_token_enabled=True,
            local_auth=BackendServiceLocalAuthConfig(
                initialize_default_user_on_empty_db=False,
            ),
            providers=[
                BackendServiceAuthProviderConfig(
                    provider_id="company-sso",
                    provider_kind="oidc",
                    display_name="Company SSO",
                    issuer_url="https://sso.example.test",
                    metadata={"audience": "frontend"},
                )
            ],
        ),
    )

    try:
        with client:
            providers_response = client.get("/api/v1/auth/providers")
            unsupported_password_login_response = client.post(
                "/api/v1/auth/login",
                json={
                    "provider_id": "company-sso",
                    "username": "demo",
                    "password": "Secret12345",
                },
            )
    finally:
        session_factory.engine.dispose()

    assert providers_response.status_code == 200
    providers_by_id = {item["provider_id"]: item for item in providers_response.json()}
    assert set(providers_by_id) == {"local", "company-sso"}
    assert providers_by_id["local"]["login_mode"] == "password"
    assert providers_by_id["local"]["supports_password_login"] is True
    assert providers_by_id["company-sso"]["provider_kind"] == "oidc"
    assert providers_by_id["company-sso"]["login_mode"] == "external-browser"
    assert providers_by_id["company-sso"]["supports_password_login"] is False
    assert providers_by_id["company-sso"]["issuer_url"] == "https://sso.example.test"
    assert providers_by_id["company-sso"]["metadata"] == {"audience": "frontend"}

    assert unsupported_password_login_response.status_code == 400
    assert unsupported_password_login_response.json()["error"]["code"] == "invalid_request"


def test_default_local_auth_initializer_skips_non_empty_user_table(tmp_path: Path) -> None:
    """验证默认本地用户初始化只在空库时执行，不覆盖已有用户态。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="default-local-auth-skip-non-empty.db",
    )
    service = LocalAuthService(
        settings=BackendServiceSettings(),
        session_factory=session_factory,
    )
    existing_user_result = service.create_user(
        LocalAuthUserCreateRequest(
            username="existing-admin",
            password="Existing12345",
            display_name="Existing Admin",
            scopes=("*",),
        )
    )
    assert existing_user_result.initial_user_token is not None

    application = create_app(
        settings=BackendServiceSettings(
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )

    try:
        with TestClient(application) as client:
            default_user_response = client.get(
                "/api/v1/system/me",
                headers=build_bearer_headers(DEFAULT_LOCAL_AUTH_TOKEN),
            )
            existing_user_response = client.get(
                "/api/v1/system/me",
                headers=build_bearer_headers(existing_user_result.initial_user_token.token),
            )
    finally:
        session_factory.engine.dispose()

    assert default_user_response.status_code == 401
    assert default_user_response.json()["error"]["code"] == "authentication_required"
    assert existing_user_response.status_code == 200
    assert existing_user_response.json()["username"] == "existing-admin"


def test_auth_events_websocket_streams_session_and_user_token_audit_events(tmp_path: Path) -> None:
    """验证 auth.events 会推送 session 与 user token 的审计事件。"""

    client, session_factory = _create_local_auth_test_client(
        tmp_path,
        database_name="auth-events-websocket.db",
    )

    try:
        with client:
            bootstrap_response = client.post(
                "/api/v1/auth/bootstrap-admin",
                json={
                    "username": "admin",
                    "password": "Admin12345",
                    "display_name": "Local Admin",
                },
            )
            bootstrap_payload = bootstrap_response.json()
            admin_headers = {"Authorization": f"Bearer {bootstrap_payload['access_token']}"}
            with client.websocket_connect(
                "/ws/v1/auth/events",
                headers=admin_headers,
            ) as websocket:
                connected_message = websocket.receive_json()

                create_user_response = client.post(
                    "/api/v1/auth/users",
                    headers=admin_headers,
                    json={
                        "username": "viewer",
                        "password": "Viewer12345",
                        "display_name": "Workflow Viewer",
                        "project_ids": ["project-1"],
                        "scopes": ["workflows:read"],
                    },
                )
                viewer_user_id = create_user_response.json()["user"]["user_id"]
                default_user_token_event = websocket.receive_json()

                viewer_login_response = client.post(
                    "/api/v1/auth/login",
                    json={
                        "provider_id": "local",
                        "username": "viewer",
                        "password": "Viewer12345",
                    },
                )
                viewer_login_payload = viewer_login_response.json()
                session_issued_event = websocket.receive_json()

                refresh_response = client.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": viewer_login_payload["refresh_token"]},
                )
                session_revoked_event = websocket.receive_json()
                refreshed_session_issued_event = websocket.receive_json()

                issue_token_response = client.post(
                    f"/api/v1/auth/users/{viewer_user_id}/tokens",
                    headers=admin_headers,
                    json={"token_name": "robot"},
                )
                issue_token_payload = issue_token_response.json()
                explicit_user_token_event = websocket.receive_json()

                revoke_token_response = client.delete(
                    f"/api/v1/auth/users/{viewer_user_id}/tokens/{issue_token_payload['token_id']}",
                    headers=admin_headers,
                )
                revoked_user_token_event = websocket.receive_json()
    finally:
        session_factory.engine.dispose()

    assert bootstrap_response.status_code == 201
    assert connected_message["event_type"] == "auth.connected"
    assert connected_message["stream"] == "auth.events"

    assert create_user_response.status_code == 201
    assert default_user_token_event["event_type"] == "auth.user-tokens.issued"
    assert default_user_token_event["payload"]["provider_id"] == "local"
    assert default_user_token_event["payload"]["user_id"] == viewer_user_id
    assert default_user_token_event["payload"]["actor_user_id"] == bootstrap_payload["user"]["user_id"]
    assert default_user_token_event["payload"]["credential_kind"] == "user-token"
    assert default_user_token_event["payload"]["token_name"] == "default"

    assert viewer_login_response.status_code == 200
    assert session_issued_event["event_type"] == "auth.sessions.issued"
    assert session_issued_event["payload"]["user_id"] == viewer_user_id
    assert session_issued_event["payload"]["credential_kind"] == "session"
    assert session_issued_event["payload"]["auth_source"] == "local-login"

    assert refresh_response.status_code == 200
    assert session_revoked_event["event_type"] == "auth.sessions.revoked"
    assert session_revoked_event["payload"]["user_id"] == viewer_user_id
    assert session_revoked_event["payload"]["revocation_reason"] == "refresh-rotated"
    assert refreshed_session_issued_event["event_type"] == "auth.sessions.issued"
    assert refreshed_session_issued_event["payload"]["user_id"] == viewer_user_id
    assert refreshed_session_issued_event["payload"]["auth_source"] == "local-refresh"

    assert issue_token_response.status_code == 201
    assert explicit_user_token_event["event_type"] == "auth.user-tokens.issued"
    assert explicit_user_token_event["payload"]["user_id"] == viewer_user_id
    assert explicit_user_token_event["payload"]["token_name"] == "robot"

    assert revoke_token_response.status_code == 204
    assert revoked_user_token_event["event_type"] == "auth.user-tokens.revoked"
    assert revoked_user_token_event["payload"]["user_id"] == viewer_user_id
    assert revoked_user_token_event["payload"]["token_name"] == "robot"
    assert revoked_user_token_event["payload"]["revocation_reason"] == "manual-revoke"


def test_local_auth_admin_can_manage_long_lived_user_tokens(tmp_path: Path) -> None:
    """验证管理员可创建、列出、撤销长期调用 user token。"""

    client, session_factory = _create_local_auth_test_client(
        tmp_path,
        database_name="local-auth-manage-user-tokens.db",
    )

    try:
        with client:
            bootstrap_response = client.post(
                "/api/v1/auth/bootstrap-admin",
                json={
                    "username": "admin",
                    "password": "Admin12345",
                    "display_name": "Local Admin",
                },
            )
            admin_payload = bootstrap_response.json()
            admin_headers = {"Authorization": f"Bearer {admin_payload['access_token']}"}
            create_user_response = client.post(
                "/api/v1/auth/users",
                headers=admin_headers,
                json={
                    "username": "operator",
                    "password": "Operator12345",
                    "display_name": "Line Operator",
                    "project_ids": ["project-1"],
                    "scopes": ["workflows:read"],
                },
            )
            user_id = create_user_response.json()["user"]["user_id"]
            create_user_token_response = client.post(
                f"/api/v1/auth/users/{user_id}/tokens",
                headers=admin_headers,
                json={
                    "token_name": "tablet",
                    "ttl_hours": 24,
                    "metadata": {"channel": "workstation"},
                },
            )
            issued_user_token_payload = create_user_token_response.json()
            extra_user_token = issued_user_token_payload["token"]
            list_tokens_response = client.get(
                f"/api/v1/auth/users/{user_id}/tokens",
                headers=admin_headers,
            )
            token_me_response = client.get(
                "/api/v1/system/me",
                headers={"Authorization": f"Bearer {extra_user_token}"},
            )
            revoke_user_token_response = client.delete(
                f"/api/v1/auth/users/{user_id}/tokens/{issued_user_token_payload['token_id']}",
                headers=admin_headers,
            )
            token_me_after_revoke_response = client.get(
                "/api/v1/system/me",
                headers={"Authorization": f"Bearer {extra_user_token}"},
            )
    finally:
        session_factory.engine.dispose()

    assert bootstrap_response.status_code == 201
    assert create_user_response.status_code == 201
    assert create_user_token_response.status_code == 201
    assert issued_user_token_payload["token_name"] == "tablet"
    assert issued_user_token_payload["expires_at"] is not None
    assert issued_user_token_payload["created_by_user_id"] == admin_payload["user"]["user_id"]
    assert issued_user_token_payload["metadata"] == {"channel": "workstation"}

    assert list_tokens_response.status_code == 200
    listed_token_names = [item["token_name"] for item in list_tokens_response.json()]
    assert listed_token_names == ["tablet", "default"]

    assert token_me_response.status_code == 200
    assert token_me_response.json()["auth_credential_kind"] == "user-token"
    assert token_me_response.json()["auth_token_name"] == "tablet"

    assert revoke_user_token_response.status_code == 204
    assert token_me_after_revoke_response.status_code == 401
    assert token_me_after_revoke_response.json()["error"]["code"] == "authentication_required"


def test_local_auth_admin_can_reset_password_and_delete_user(tmp_path: Path) -> None:
    """验证管理员可重置密码，并在删除用户后让会话与长期 token 全部失效。"""

    client, session_factory = _create_local_auth_test_client(
        tmp_path,
        database_name="local-auth-reset-and-delete.db",
    )

    try:
        with client:
            bootstrap_response = client.post(
                "/api/v1/auth/bootstrap-admin",
                json={
                    "username": "admin",
                    "password": "Admin12345",
                    "display_name": "Local Admin",
                },
            )
            admin_headers = {"Authorization": f"Bearer {bootstrap_response.json()['access_token']}"}
            create_user_response = client.post(
                "/api/v1/auth/users",
                headers=admin_headers,
                json={
                    "username": "viewer",
                    "password": "Viewer12345",
                    "display_name": "Workflow Viewer",
                    "project_ids": ["project-1"],
                    "scopes": ["workflows:read"],
                },
            )
            create_user_payload = create_user_response.json()
            viewer_user_id = create_user_payload["user"]["user_id"]
            viewer_user_token = create_user_payload["initial_user_token"]["token"]
            reset_password_response = client.post(
                f"/api/v1/auth/users/{viewer_user_id}/reset-password",
                headers=admin_headers,
                json={
                    "new_password": "Viewer22345",
                    "revoke_sessions": True,
                    "revoke_user_tokens": False,
                },
            )
            old_login_response = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "viewer",
                    "password": "Viewer12345",
                },
            )
            new_login_response = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "viewer",
                    "password": "Viewer22345",
                },
            )
            user_token_me_response = client.get(
                "/api/v1/system/me",
                headers={"Authorization": f"Bearer {viewer_user_token}"},
            )
            delete_user_response = client.delete(
                f"/api/v1/auth/users/{viewer_user_id}",
                headers=admin_headers,
            )
            deleted_user_token_me_response = client.get(
                "/api/v1/system/me",
                headers={"Authorization": f"Bearer {viewer_user_token}"},
            )
            deleted_user_login_response = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "viewer",
                    "password": "Viewer22345",
                },
            )
    finally:
        session_factory.engine.dispose()

    assert bootstrap_response.status_code == 201
    assert create_user_response.status_code == 201
    assert reset_password_response.status_code == 200
    assert reset_password_response.json()["user_id"] == viewer_user_id

    assert old_login_response.status_code == 401
    assert old_login_response.json()["error"]["code"] == "authentication_required"
    assert new_login_response.status_code == 200
    assert new_login_response.json()["user"]["user_id"] == viewer_user_id

    assert user_token_me_response.status_code == 200
    assert user_token_me_response.json()["auth_credential_kind"] == "user-token"

    assert delete_user_response.status_code == 204
    assert deleted_user_token_me_response.status_code == 401
    assert deleted_user_token_me_response.json()["error"]["code"] == "authentication_required"
    assert deleted_user_login_response.status_code == 401
    assert deleted_user_login_response.json()["error"]["code"] == "authentication_required"


def _create_local_auth_test_client(
    tmp_path: Path,
    *,
    database_name: str,
    auth_config: BackendServiceAuthConfig | None = None,
) -> tuple[TestClient, object]:
    """创建启用 local auth 模式的测试客户端。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name=database_name,
    )
    application = create_app(
        settings=BackendServiceSettings(
            auth=auth_config
            if auth_config is not None
            else BackendServiceAuthConfig(
                mode="local",
                websocket_query_token_enabled=True,
                local_auth=BackendServiceLocalAuthConfig(
                    initialize_default_user_on_empty_db=False,
                ),
            ),
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    return TestClient(application), session_factory