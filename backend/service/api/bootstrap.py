"""backend-service 启动编排。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI

from backend.bootstrap.core import BootstrapStep, RuntimeBootstrap
from backend.service.api.seeders import BackendServiceSeeder, BackendServiceSeederRunner
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.settings import BackendServiceSettings, get_backend_service_settings


@dataclass(frozen=True)
class BackendServiceRuntime:
    """描述 backend-service 启动后持有的基础运行时资源。

    字段：
    - settings：当前 backend-service 进程使用的统一配置。
    - session_factory：数据库会话工厂。
    - dataset_storage：本地数据集文件存储服务。
    """

    settings: BackendServiceSettings
    session_factory: SessionFactory
    dataset_storage: LocalDatasetStorage


class InitializeDatabaseSchemaStep:
    """执行 backend-service 数据库 schema 初始化步骤。"""

    def get_step_name(self) -> str:
        """返回当前步骤名称。

        返回：
        - 当前步骤的稳定名称。
        """

        return "initialize-database-schema"

    def run(self, runtime: BackendServiceRuntime) -> None:
        """确保数据库文件和当前 ORM 对应的数据表就绪。

        参数：
        - runtime：当前应用实例使用的运行时资源。
        """

        initialize_database_schema(runtime.session_factory)


class RunBackendServiceSeedersStep:
    """执行 backend-service seeders 的 bootstrap 步骤。"""

    def __init__(self, seeders: tuple[BackendServiceSeeder, ...]) -> None:
        """初始化 seeder 步骤。

        参数：
        - seeders：当前 backend-service 启动流程使用的 seeder 元组。
        """

        self._seeders = seeders

    def get_step_name(self) -> str:
        """返回当前步骤名称。

        返回：
        - 当前步骤的稳定名称。
        """

        return "run-service-seeders"

    def run(self, runtime: BackendServiceRuntime) -> None:
        """执行 backend-service 启动期需要的独立 seeder 步骤。

        参数：
        - runtime：当前应用实例使用的运行时资源。

        说明：
        - seeder 的接口和执行顺序独立于 bootstrap 主流程定义。
        - 后续默认系统记录、内建 capability 索引等幂等初始化应以独立 seeder 落地。
        """

        BackendServiceSeederRunner(self._seeders).run(runtime)


class LoadBackendServicePluginCatalogStep:
    """加载 backend-service 插件目录元数据的步骤。"""

    def get_step_name(self) -> str:
        """返回当前步骤名称。

        返回：
        - 当前步骤的稳定名称。
        """

        return "load-service-plugin-catalog"

    def run(self, runtime: BackendServiceRuntime) -> None:
        """执行 backend-service 插件目录元数据准备步骤。

        参数：
        - runtime：当前应用实例使用的运行时资源。

        说明：
        - 当前仓库还没有正式接入 PluginLoader 和插件目录扫描。
        - 后续插件 manifest、capability 索引和启用状态读取可放在这里。
        """

        _ = runtime


class BackendServiceBootstrap(RuntimeBootstrap[BackendServiceSettings, BackendServiceRuntime]):
    """按固定步骤准备 backend-service 运行环境。"""

    def __init__(
        self,
        *,
        settings: BackendServiceSettings | None = None,
        session_factory: SessionFactory | None = None,
        dataset_storage: LocalDatasetStorage | None = None,
        seeders: tuple[BackendServiceSeeder, ...] | None = None,
    ) -> None:
        """初始化启动编排器。

        参数：
        - settings：可选的统一配置对象。
        - session_factory：可选的数据库会话工厂。
        - dataset_storage：可选的数据集本地文件存储服务。
        - seeders：可选的启动期 seeder 列表。
        """

        self._provided_settings = settings
        self._provided_session_factory = session_factory
        self._provided_dataset_storage = dataset_storage
        self._provided_seeders = seeders

    def load_settings(self) -> BackendServiceSettings:
        """读取 backend-service 的统一配置。

        返回：
        - 当前启动流程使用的 BackendServiceSettings。
        """

        return self._provided_settings or get_backend_service_settings()

    def build_runtime(self, settings: BackendServiceSettings) -> BackendServiceRuntime:
        """根据统一配置解析 backend-service 的基础运行时资源。

        参数：
        - settings：当前启动流程使用的统一配置。

        返回：
        - 当前应用实例要绑定的运行时资源。
        """

        return BackendServiceRuntime(
            settings=settings,
            session_factory=self._provided_session_factory
            or SessionFactory(settings.to_database_settings()),
            dataset_storage=self._provided_dataset_storage
            or LocalDatasetStorage(settings.to_dataset_storage_settings()),
        )

    def bind_application_state(
        self,
        application: FastAPI,
        runtime: BackendServiceRuntime,
    ) -> None:
        """把运行时资源绑定到 FastAPI application.state。

        参数：
        - application：当前 FastAPI 应用。
        - runtime：当前应用实例使用的运行时资源。
        """

        application.state.backend_service_settings = runtime.settings
        application.state.session_factory = runtime.session_factory
        application.state.dataset_storage = runtime.dataset_storage

    def _build_steps(self) -> tuple[BootstrapStep[BackendServiceRuntime], ...]:
        """返回当前 backend-service 启动链要执行的步骤元组。

        返回：
        - 当前 backend-service 启动链的步骤元组。

        说明：
        - 配置加载是 bootstrap 的第一步，在 build_runtime 之前完成。
        - 当前服务进程只执行适合 backend-service 的轻量启动步骤。
        - 当前启动顺序为：数据库 -> seeders -> 插件目录元数据。
        """

        return (
            InitializeDatabaseSchemaStep(),
            RunBackendServiceSeedersStep(self._build_seeders()),
            LoadBackendServicePluginCatalogStep(),
        )

    def _build_seeders(self) -> tuple[BackendServiceSeeder, ...]:
        """返回当前 backend-service 启动流程要执行的 seeders。

        返回：
        - 当前启动流程使用的 seeder 元组。
        """

        return self._provided_seeders or ()