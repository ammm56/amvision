"""backend-service 启动编排。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI

from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class BackendServiceRuntime:
    """描述 backend-service 启动后持有的基础运行时资源。

    字段：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地数据集文件存储服务。
    """

    session_factory: SessionFactory
    dataset_storage: LocalDatasetStorage


class BackendServiceBootstrap:
    """按固定步骤准备 backend-service 运行环境。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        dataset_storage: LocalDatasetStorage | None = None,
    ) -> None:
        """初始化启动编排器。

        参数：
        - session_factory：可选的数据库会话工厂。
        - dataset_storage：可选的数据集本地文件存储服务。
        """

        self._provided_session_factory = session_factory
        self._provided_dataset_storage = dataset_storage

    def build_runtime(self) -> BackendServiceRuntime:
        """解析 backend-service 的基础运行时资源。

        返回：
        - 当前应用实例要绑定的运行时资源。
        """

        return BackendServiceRuntime(
            session_factory=self._provided_session_factory or SessionFactory(DatabaseSettings()),
            dataset_storage=self._provided_dataset_storage
            or LocalDatasetStorage(DatasetStorageSettings()),
        )

    def initialize(self, runtime: BackendServiceRuntime) -> None:
        """执行服务正式运行前的初始化步骤。

        参数：
        - runtime：当前应用实例使用的运行时资源。

        说明：
        - 当前顺序只包含数据库 schema 初始化。
        - 后续统一配置加载、seed data、插件注册等服务级启动步骤可继续落在这里。
        """

        self._initialize_database(runtime)

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

        application.state.session_factory = runtime.session_factory
        application.state.dataset_storage = runtime.dataset_storage

    def _initialize_database(self, runtime: BackendServiceRuntime) -> None:
        """确保数据库文件和当前 ORM 对应的数据表就绪。"""

        initialize_database_schema(runtime.session_factory)