"""FastAPI 依赖注入链最小行为测试。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.api.app import create_app
from backend.service.api.bootstrap import BackendServiceBootstrap
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.settings import (
    BackendServiceAppSettings,
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceQueueConfig,
    BackendServiceSettings,
    BackendServiceTaskManagerConfig,
    get_backend_service_settings,
)


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


def test_create_app_uses_explicit_backend_service_settings(tmp_path: Path) -> None:
    """验证 create_app 会使用显式传入的统一配置。"""

    storage_root = tmp_path / "files"
    settings = BackendServiceSettings(
        app=BackendServiceAppSettings(
            app_name="amvision test-service",
            app_version="0.2.0",
        ),
        database=BackendServiceDatabaseConfig(
            url=f"sqlite:///{(tmp_path / 'explicit.db').as_posix()}"
        ),
        dataset_storage=BackendServiceDatasetStorageConfig(root_dir=str(storage_root)),
        queue=BackendServiceQueueConfig(root_dir=str(tmp_path / "queue-root")),
        task_manager=BackendServiceTaskManagerConfig(enabled=False),
    )

    application = create_app(settings=settings)
    try:
        assert application.title == "amvision test-service"
        assert application.version == "0.2.0"
        assert application.state.backend_service_settings == settings
        assert application.state.dataset_storage.root_dir == storage_root.resolve()
        assert application.state.queue_backend.root_dir == (tmp_path / "queue-root").resolve()
        assert application.state.background_task_manager_host is None
    finally:
        application.state.session_factory.engine.dispose()


def test_get_backend_service_settings_reads_json_files_and_environment_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证统一配置模块会先读 config JSON，再接受环境变量覆盖。"""

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "backend-service.json").write_text(
        json.dumps(
            {
                "app": {
                    "app_name": "amvision config-service",
                    "app_version": "0.3.0",
                },
                "database": {
                    "url": "sqlite:///./data/from-config.db",
                    "echo": False,
                },
                "dataset_storage": {
                    "root_dir": "./data/from-config-files",
                },
                "queue": {
                    "root_dir": "./data/from-config-queue",
                },
                "task_manager": {
                    "enabled": False,
                    "max_concurrent_tasks": 3,
                    "poll_interval_seconds": 2.0,
                },
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "backend-service.local.json").write_text(
        json.dumps(
            {
                "app": {
                    "app_version": "0.3.1-local",
                },
                "dataset_storage": {
                    "root_dir": "./data/from-local-config-files",
                },
                "queue": {
                    "root_dir": "./data/from-local-config-queue",
                },
                "task_manager": {
                    "max_concurrent_tasks": 4,
                },
            }
        ),
        encoding="utf-8",
    )

    get_backend_service_settings.cache_clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AMVISION_APP__APP_NAME", "amvision env-service")
    monkeypatch.setenv("AMVISION_DATABASE__ECHO", "true")
    monkeypatch.setenv("AMVISION_TASK_MANAGER__ENABLED", "true")

    settings = get_backend_service_settings()

    assert settings.app.app_name == "amvision env-service"
    assert settings.app.app_version == "0.3.1-local"
    assert settings.database.echo is True
    assert settings.database.url == "sqlite:///./data/from-config.db"
    assert settings.dataset_storage.root_dir == "./data/from-local-config-files"
    assert settings.queue.root_dir == "./data/from-local-config-queue"
    assert settings.task_manager.enabled is True
    assert settings.task_manager.max_concurrent_tasks == 4
    assert settings.task_manager.poll_interval_seconds == 2.0

    get_backend_service_settings.cache_clear()


def test_bootstrap_runs_explicit_seeders_in_initialize(tmp_path: Path) -> None:
    """验证 bootstrap.initialize 会按顺序执行显式传入的 seeders。"""

    settings = BackendServiceSettings(
        app=BackendServiceAppSettings(app_name="amvision seeded-service"),
        database=BackendServiceDatabaseConfig(
            url=f"sqlite:///{(tmp_path / 'seeded.db').as_posix()}"
        ),
        dataset_storage=BackendServiceDatasetStorageConfig(
            root_dir=str(tmp_path / "seeded-files")
        ),
    )
    recorded_steps: list[str] = []

    class RecordingSeeder:
        """记录执行顺序的测试 seeder。"""

        def get_step_name(self) -> str:
            """返回当前测试 seeder 的步骤名。"""

            return "recording-seeder"

        def seed(self, runtime) -> None:
            """记录 bootstrap 传入的运行时信息。

            参数：
            - runtime：当前 backend-service 进程使用的运行时资源。
            """

            recorded_steps.append(runtime.settings.app.app_name)

    bootstrap = BackendServiceBootstrap(
        settings=settings,
        seeders=(RecordingSeeder(),),
    )
    runtime = bootstrap.build_runtime(bootstrap.load_settings())
    try:
        bootstrap.initialize(runtime)
        assert recorded_steps == ["amvision seeded-service"]
        assert bootstrap.get_step_names() == (
            "initialize-database-schema",
            "run-service-seeders",
            "load-service-plugin-catalog",
        )
    finally:
        runtime.session_factory.engine.dispose()


def test_app_lifespan_starts_and_stops_background_task_manager(tmp_path: Path) -> None:
    """验证 backend-service 生命周期会统一启动和停止内嵌 task manager。"""

    settings = BackendServiceSettings(
        database=BackendServiceDatabaseConfig(
            url=f"sqlite:///{(tmp_path / 'hosted.db').as_posix()}"
        ),
        dataset_storage=BackendServiceDatasetStorageConfig(
            root_dir=str(tmp_path / "hosted-files")
        ),
        queue=BackendServiceQueueConfig(root_dir=str(tmp_path / "hosted-queue")),
        task_manager=BackendServiceTaskManagerConfig(
            enabled=True,
            max_concurrent_tasks=1,
            poll_interval_seconds=0.1,
        ),
    )
    application = create_app(settings=settings)
    background_task_manager_host = application.state.background_task_manager_host

    assert background_task_manager_host is not None
    assert background_task_manager_host.is_running is False

    with TestClient(application):
        assert background_task_manager_host.is_running is True

    assert background_task_manager_host.is_running is False


def _create_test_client() -> TestClient:
    """创建使用内存 SQLite 的测试客户端。

    返回：
    - 绑定内存数据库的 TestClient。
    """

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    return TestClient(create_app(session_factory=session_factory))