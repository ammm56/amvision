"""FastAPI 依赖注入链最小行为测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.api.app import create_app
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory


def test_health_route_returns_request_id_header() -> None:
    """验证健康检查接口会透传 request_id。"""

    with _create_test_client() as client:
        response = client.get("/api/v1/system/health", headers={"x-request-id": "request-1"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "request-1"
    assert response.json()["request_id"] == "request-1"


def test_me_route_requires_principal() -> None:
    """验证需要鉴权的接口在缺少主体时返回统一 401。"""

    with _create_test_client() as client:
        response = client.get("/api/v1/system/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_me_route_reads_principal_from_headers() -> None:
    """验证请求头中的主体信息会被鉴权依赖解析。"""

    with _create_test_client() as client:
        response = client.get(
            "/api/v1/system/me",
            headers={
                "x-amvision-principal-id": "user-1",
                "x-amvision-principal-type": "user",
                "x-amvision-project-ids": "project-1, project-2",
                "x-amvision-scopes": "system:read, datasets:write",
            },
        )

    assert response.status_code == 200
    assert response.json()["principal_id"] == "user-1"
    assert response.json()["project_ids"] == ["project-1", "project-2"]
    assert response.json()["scopes"] == ["system:read", "datasets:write"]


def test_database_route_checks_scope_and_uses_unit_of_work() -> None:
    """验证数据库接口会执行 scope 检查并通过 Unit of Work 访问数据库。"""

    with _create_test_client() as client:
        denied_response = client.get(
            "/api/v1/system/database",
            headers={
                "x-amvision-principal-id": "user-1",
                "x-amvision-scopes": "datasets:read",
            },
        )
        allowed_response = client.get(
            "/api/v1/system/database",
            headers={
                "x-amvision-principal-id": "user-1",
                "x-amvision-scopes": "system:read",
            },
        )

    assert denied_response.status_code == 403
    assert denied_response.json()["error"]["code"] == "permission_denied"
    assert allowed_response.status_code == 200
    assert allowed_response.json()["database"] == "reachable"
    assert allowed_response.json()["scalar"] == 1


def test_app_startup_initializes_missing_database_tables(tmp_path: Path) -> None:
    """验证 FastAPI 应用启动时会初始化缺失的数据表。"""

    database_path = tmp_path / "startup.db"
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
    try:
        with TestClient(create_app(session_factory=session_factory)):
            pass

        connection = sqlite3.connect(database_path)
        try:
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            connection.close()

        assert "dataset_imports" in table_names
        assert "dataset_versions" in table_names
        assert "models" in table_names
        assert "model_files" in table_names
    finally:
        session_factory.engine.dispose()


def _create_test_client() -> TestClient:
    """创建使用内存 SQLite 的测试客户端。

    返回：
    - 绑定内存数据库的 TestClient。
    """

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    return TestClient(create_app(session_factory=session_factory))