"""浏览器接入边界相关 API 测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.api.app import create_app
from backend.service.settings import (
    BackendServiceAuthConfig,
    BackendServiceSettings,
    BackendServiceStaticAccessTokenConfig,
)
from tests.api_test_support import create_test_runtime


def test_system_me_accepts_static_bearer_token_and_reports_auth_source(tmp_path: Path) -> None:
    """验证 HTTP 接口支持静态 Bearer token，并返回实际鉴权来源。"""

    client, session_factory = _create_access_boundary_test_client(
        tmp_path,
        database_name="api-access-boundary-http.db",
    )

    try:
        with client:
            response = client.get(
                "/api/v1/system/me",
                headers={"Authorization": "Bearer frontend-token"},
            )
    finally:
        session_factory.engine.dispose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["principal_id"] == "frontend-user"
    assert payload["project_ids"] == ["project-1"]
    assert payload["auth_source"] == "bearer-token"
    assert payload["auth_mode"] == "hybrid"


def test_projects_events_websocket_accepts_query_access_token(tmp_path: Path) -> None:
    """验证浏览器可用的 WebSocket query token 可以建立 projects 资源流连接。"""

    client, session_factory = _create_access_boundary_test_client(
        tmp_path,
        database_name="api-access-boundary-ws.db",
    )

    try:
        with client:
            with client.websocket_connect(
                "/ws/v1/projects/events?project_id=project-1&access_token=frontend-token"
            ) as websocket:
                connected_message = websocket.receive_json()
                snapshot_message = websocket.receive_json()
    finally:
        session_factory.engine.dispose()

    assert connected_message["event_type"] == "projects.connected"
    assert snapshot_message["event_type"] == "projects.summary.snapshot"
    assert snapshot_message["resource_id"] == "project-1"


def test_localhost_cors_preflight_is_allowed(tmp_path: Path) -> None:
    """验证 localhost 前端开发服务器的 CORS 预检会被允许。"""

    client, session_factory = _create_access_boundary_test_client(
        tmp_path,
        database_name="api-access-boundary-cors.db",
    )

    try:
        with client:
            response = client.options(
                "/api/v1/system/health",
                headers={
                    "Origin": "http://127.0.0.1:5173",
                    "Access-Control-Request-Method": "GET",
                },
            )
    finally:
        session_factory.engine.dispose()

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def _create_access_boundary_test_client(
    tmp_path: Path,
    *,
    database_name: str,
) -> tuple[TestClient, object]:
    """创建带静态 Bearer token 配置的测试客户端。

    参数：
    - tmp_path：pytest 临时目录。
    - database_name：SQLite 数据库文件名。

    返回：
    - tuple[TestClient, object]：测试客户端和数据库会话工厂。
    """

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name=database_name,
    )
    application = create_app(
        settings=BackendServiceSettings(
            auth=BackendServiceAuthConfig(
                mode="hybrid",
                allow_development_headers=True,
                websocket_query_token_enabled=True,
                static_tokens=[
                    BackendServiceStaticAccessTokenConfig(
                        token="frontend-token",
                        principal_id="frontend-user",
                        principal_type="service-account",
                        project_ids=["project-1"],
                        scopes=["workflows:read", "models:read"],
                    )
                ],
            )
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    return TestClient(application), session_factory