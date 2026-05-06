"""backend-service 统一配置定义。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from backend.bootstrap.settings import build_json_config_sources
from backend.queue import LocalFileQueueSettings
from backend.service.application.runtime.deployment_process_settings import (
    DeploymentProcessSupervisorConfig,
)
from backend.service.infrastructure.db.session import DatabaseSettings
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
)


CONFIG_DIR = Path("config")
BACKEND_SERVICE_CONFIG_FILE = CONFIG_DIR / "backend-service.json"
BACKEND_SERVICE_LOCAL_CONFIG_FILE = CONFIG_DIR / "backend-service.local.json"


class BackendServiceAppSettings(BaseModel):
    """描述 backend-service 自身的基础应用配置。

    字段：
    - app_name：FastAPI 应用标题。
    - app_version：FastAPI 应用版本号。
    """

    app_name: str = "amvision backend-service"
    app_version: str = "0.1.0"


class BackendServiceDatabaseConfig(BaseModel):
    """描述 backend-service 使用的数据库配置。

    字段：
    - url：数据库连接串。
    - echo：是否输出 SQL 日志。
    """

    url: str = "sqlite:///./data/amvision.db"
    echo: bool = False


class BackendServiceDatasetStorageConfig(BaseModel):
    """描述 backend-service 使用的本地文件存储配置。

    字段：
    - root_dir：数据集文件根目录。
    """

    root_dir: str = "./data/files"


class BackendServiceQueueConfig(BaseModel):
    """描述 backend-service 使用的本地队列配置。

    字段：
    - root_dir：队列根目录。
    """

    root_dir: str = "./data/queue"


class BackendServiceTaskManagerConfig(BaseModel):
    """描述 backend-service 托管后台任务管理器的配置。

    字段：
    - enabled：是否在 backend-service 进程内自动启动 task manager。
    - max_concurrent_tasks：后台任务最大并发数。
    - poll_interval_seconds：空闲轮询间隔秒数。
    """

    enabled: bool = True
    max_concurrent_tasks: int = 2
    poll_interval_seconds: float = 1.0


class BackendServiceSettings(BaseSettings):
    """描述 backend-service 启动阶段使用的统一配置。

    字段：
    - app：FastAPI 应用基础配置。
    - database：数据库连接配置。
    - dataset_storage：本地数据集文件存储配置。
    - queue：本地任务队列配置。
    - task_manager：内嵌后台任务管理器配置。
    - deployment_process_supervisor：deployment 进程监督器配置。
    """

    model_config = SettingsConfigDict(
        env_prefix="AMVISION_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app: BackendServiceAppSettings = Field(default_factory=BackendServiceAppSettings)
    database: BackendServiceDatabaseConfig = Field(default_factory=BackendServiceDatabaseConfig)
    dataset_storage: BackendServiceDatasetStorageConfig = Field(
        default_factory=BackendServiceDatasetStorageConfig
    )
    queue: BackendServiceQueueConfig = Field(default_factory=BackendServiceQueueConfig)
    task_manager: BackendServiceTaskManagerConfig = Field(
        default_factory=BackendServiceTaskManagerConfig
    )
    deployment_process_supervisor: DeploymentProcessSupervisorConfig = Field(
        default_factory=DeploymentProcessSupervisorConfig
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """定义统一配置的加载优先级。

        参数：
        - settings_cls：当前 Settings 类型。
        - init_settings：显式传入构造参数的配置源。
        - env_settings：环境变量配置源。
        - dotenv_settings：dotenv 配置源。
        - file_secret_settings：file secret 配置源。

        返回：
        - 按优先级排列的配置源元组。

        说明：
        - 当前项目本地优先，默认先从 config 目录读取 JSON 配置。
        - 环境变量保留为覆盖层，便于调试、测试和部署时临时改写。
        - 显式传参仍保持最高优先级，便于测试和 launcher 注入。
        """

        return (
            init_settings,
            env_settings,
            *build_json_config_sources(
                settings_cls,
                (BACKEND_SERVICE_LOCAL_CONFIG_FILE, BACKEND_SERVICE_CONFIG_FILE),
            ),
            dotenv_settings,
            file_secret_settings,
        )

    def to_database_settings(self) -> DatabaseSettings:
        """把统一配置转换为数据库连接配置。

        返回：
        - 供 SessionFactory 使用的 DatabaseSettings。
        """

        return DatabaseSettings(
            url=self.database.url,
            echo=self.database.echo,
        )

    def to_dataset_storage_settings(self) -> DatasetStorageSettings:
        """把统一配置转换为本地文件存储配置。

        返回：
        - 供 LocalDatasetStorage 使用的 DatasetStorageSettings。
        """

        return DatasetStorageSettings(root_dir=self.dataset_storage.root_dir)

    def to_queue_settings(self) -> LocalFileQueueSettings:
        """把统一配置转换为本地队列配置。

        返回：
        - 供 LocalFileQueueBackend 使用的 LocalFileQueueSettings。
        """

        return LocalFileQueueSettings(root_dir=self.queue.root_dir)


@lru_cache
def get_backend_service_settings() -> BackendServiceSettings:
    """读取并缓存 backend-service 的统一配置。

    返回：
    - 当前进程共享的 BackendServiceSettings。
    """

    return BackendServiceSettings()
