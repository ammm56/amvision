"""worker 与 maintenance 启动链最小行为测试。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.maintenance.bootstrap import BackendMaintenanceBootstrap
from backend.maintenance.settings import (
    BackendMaintenanceAppSettings,
    BackendMaintenanceSettings,
    BackendMaintenanceWorkspaceConfig,
    get_backend_maintenance_settings,
)
from backend.workers.bootstrap import BackendWorkerBootstrap
from backend.workers.settings import (
    BackendWorkerAppSettings,
    BackendWorkerDatasetStorageConfig,
    BackendWorkerDatabaseConfig,
    BackendWorkerQueueConfig,
    BackendWorkerSettings,
    BackendWorkerWorkspaceConfig,
    get_backend_worker_settings,
)


def test_get_backend_worker_settings_reads_json_files_and_environment_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 worker 配置会先读 config JSON，再接受环境变量覆盖。"""

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "backend-worker.json").write_text(
        json.dumps(
            {
                "app": {
                    "app_name": "amvision config-worker",
                    "app_version": "0.2.0",
                },
                "workspace": {
                    "root_dir": "./data/from-worker-config",
                },
                "queue": {
                    "root_dir": "./data/from-worker-queue-config",
                    "max_concurrent_tasks": 3,
                    "poll_interval_seconds": 2.5,
                },
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "backend-worker.local.json").write_text(
        json.dumps(
            {
                "app": {
                    "app_version": "0.2.1-local",
                },
            }
        ),
        encoding="utf-8",
    )

    get_backend_worker_settings.cache_clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AMVISION_WORKER_APP__APP_NAME", "amvision env-worker")
    monkeypatch.setenv("AMVISION_WORKER_WORKSPACE__ROOT_DIR", "./data/from-worker-env")
    monkeypatch.setenv("AMVISION_WORKER_QUEUE__ROOT_DIR", "./data/from-worker-queue-env")
    monkeypatch.setenv("AMVISION_WORKER_QUEUE__MAX_CONCURRENT_TASKS", "4")

    settings = get_backend_worker_settings()

    assert settings.app.app_name == "amvision env-worker"
    assert settings.app.app_version == "0.2.1-local"
    assert settings.workspace.root_dir == "./data/from-worker-env"
    assert settings.queue.root_dir == "./data/from-worker-queue-env"
    assert settings.queue.max_concurrent_tasks == 4
    assert settings.queue.poll_interval_seconds == 2.5

    get_backend_worker_settings.cache_clear()


def test_worker_bootstrap_initializes_workspace_directory(tmp_path: Path) -> None:
    """验证 worker bootstrap 会创建工作目录并暴露步骤名称。"""

    settings = BackendWorkerSettings(
        app=BackendWorkerAppSettings(app_name="amvision explicit-worker"),
        workspace=BackendWorkerWorkspaceConfig(root_dir=str(tmp_path / "worker-root")),
        database=BackendWorkerDatabaseConfig(
            url=f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
        ),
        dataset_storage=BackendWorkerDatasetStorageConfig(
            root_dir=str(tmp_path / "dataset-files")
        ),
        queue=BackendWorkerQueueConfig(root_dir=str(tmp_path / "queue-root")),
    )
    bootstrap = BackendWorkerBootstrap(settings=settings)
    runtime = bootstrap.build_runtime(bootstrap.load_settings())

    try:
        bootstrap.initialize(runtime)

        assert runtime.workspace_dir == (tmp_path / "worker-root").resolve()
        assert runtime.workspace_dir.is_dir()
        assert runtime.dataset_storage.root_dir == (tmp_path / "dataset-files").resolve()
        assert runtime.queue_backend.root_dir == (tmp_path / "queue-root").resolve()
        assert bootstrap.get_step_names() == (
            "prepare-worker-workspace",
            "load-worker-plugin-catalog",
        )
    finally:
        runtime.session_factory.engine.dispose()


def test_get_backend_maintenance_settings_reads_json_files_and_environment_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 maintenance 配置会先读 config JSON，再接受环境变量覆盖。"""

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "backend-maintenance.json").write_text(
        json.dumps(
            {
                "app": {
                    "app_name": "amvision config-maintenance",
                    "app_version": "0.4.0",
                },
                "workspace": {
                    "root_dir": "./data/from-maintenance-config",
                },
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "backend-maintenance.local.json").write_text(
        json.dumps(
            {
                "app": {
                    "app_version": "0.4.1-local",
                },
            }
        ),
        encoding="utf-8",
    )

    get_backend_maintenance_settings.cache_clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "AMVISION_MAINTENANCE_WORKSPACE__ROOT_DIR",
        "./data/from-maintenance-env",
    )

    settings = get_backend_maintenance_settings()

    assert settings.app.app_name == "amvision config-maintenance"
    assert settings.app.app_version == "0.4.1-local"
    assert settings.workspace.root_dir == "./data/from-maintenance-env"

    get_backend_maintenance_settings.cache_clear()


def test_maintenance_bootstrap_initializes_workspace_directory(tmp_path: Path) -> None:
    """验证 maintenance bootstrap 会创建工作目录并暴露步骤名称。"""

    settings = BackendMaintenanceSettings(
        app=BackendMaintenanceAppSettings(app_name="amvision explicit-maintenance"),
        workspace=BackendMaintenanceWorkspaceConfig(
            root_dir=str(tmp_path / "maintenance-root")
        ),
    )
    bootstrap = BackendMaintenanceBootstrap(settings=settings)
    runtime = bootstrap.build_runtime(bootstrap.load_settings())

    bootstrap.initialize(runtime)

    assert runtime.workspace_dir == (tmp_path / "maintenance-root").resolve()
    assert runtime.workspace_dir.is_dir()
    assert bootstrap.get_step_names() == (
        "prepare-maintenance-workspace",
        "load-maintenance-operation-catalog",
    )