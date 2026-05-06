"""backend-worker 统一配置定义。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
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
BACKEND_WORKER_CONFIG_FILE = CONFIG_DIR / "backend-worker.json"
BACKEND_WORKER_LOCAL_CONFIG_FILE = CONFIG_DIR / "backend-worker.local.json"

BACKEND_WORKER_CONSUMER_DATASET_IMPORT = "dataset-import"
BACKEND_WORKER_CONSUMER_DATASET_EXPORT = "dataset-export"
BACKEND_WORKER_CONSUMER_YOLOX_TRAINING = "yolox-training"
BACKEND_WORKER_CONSUMER_YOLOX_CONVERSION = "yolox-conversion"
BACKEND_WORKER_CONSUMER_YOLOX_EVALUATION = "yolox-evaluation"
BACKEND_WORKER_CONSUMER_YOLOX_INFERENCE = "yolox-inference"
DEFAULT_BACKEND_WORKER_CONSUMER_KINDS = (
    BACKEND_WORKER_CONSUMER_DATASET_IMPORT,
    BACKEND_WORKER_CONSUMER_DATASET_EXPORT,
    BACKEND_WORKER_CONSUMER_YOLOX_TRAINING,
    BACKEND_WORKER_CONSUMER_YOLOX_CONVERSION,
    BACKEND_WORKER_CONSUMER_YOLOX_EVALUATION,
    BACKEND_WORKER_CONSUMER_YOLOX_INFERENCE,
)
SUPPORTED_BACKEND_WORKER_CONSUMER_KINDS = frozenset(DEFAULT_BACKEND_WORKER_CONSUMER_KINDS)


class BackendWorkerAppSettings(BaseModel):
    """描述 backend-worker 进程自身的基础配置。

    字段：
    - app_name：worker 进程名称。
    - app_version：worker 进程版本号。
    """

    app_name: str = "amvision worker"
    app_version: str = "0.1.0"


class BackendWorkerWorkspaceConfig(BaseModel):
    """描述 backend-worker 使用的工作目录配置。

    字段：
    - root_dir：worker 运行态文件根目录。
    """

    root_dir: str = "./data/worker"


class BackendWorkerDatabaseConfig(BaseModel):
    """描述 backend-worker 使用的数据库配置。

    字段：
    - url：数据库连接串。
    - echo：是否输出 SQL 日志。
    """

    url: str = "sqlite:///./data/amvision.db"
    echo: bool = False


class BackendWorkerDatasetStorageConfig(BaseModel):
    """描述 backend-worker 使用的数据集文件存储配置。

    字段：
    - root_dir：数据集文件根目录。
    """

    root_dir: str = "./data/files"


class BackendWorkerQueueConfig(BaseModel):
    """描述 backend-worker 使用的本地队列配置。

    字段：
    - root_dir：队列根目录。
    """

    root_dir: str = "./data/queue"


class BackendWorkerTaskManagerConfig(BaseModel):
    """描述 backend-worker 托管后台任务消费者的配置。

    字段：
    - enabled_consumer_kinds：当前独立 worker 需要启用的消费者种类。
    - max_concurrent_tasks：当前 worker 允许的最大并发任务数。
    - poll_interval_seconds：空闲轮询间隔秒数。
    """

    enabled_consumer_kinds: tuple[str, ...] = Field(
        default_factory=lambda: DEFAULT_BACKEND_WORKER_CONSUMER_KINDS
    )
    max_concurrent_tasks: int = 2
    poll_interval_seconds: float = 1.0

    @field_validator("enabled_consumer_kinds", mode="before")
    @classmethod
    def _normalize_enabled_consumer_kinds(cls, value: object) -> tuple[str, ...]:
        """规范化并校验当前 worker 需要启用的消费者种类。

        参数：
        - value：原始配置值。

        返回：
        - tuple[str, ...]：去重后的稳定消费者种类元组。
        """

        if value is None:
            return DEFAULT_BACKEND_WORKER_CONSUMER_KINDS
        raw_items: tuple[object, ...]
        if isinstance(value, str):
            raw_items = (value,)
        elif isinstance(value, list | tuple):
            raw_items = tuple(value)
        else:
            raise ValueError("enabled_consumer_kinds 必须是字符串列表")

        normalized_items: list[str] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, str) or not raw_item.strip():
                raise ValueError("enabled_consumer_kinds 里的每个值都必须是非空字符串")
            consumer_kind = raw_item.strip()
            if consumer_kind not in SUPPORTED_BACKEND_WORKER_CONSUMER_KINDS:
                raise ValueError(f"不支持的 worker consumer kind: {consumer_kind}")
            if consumer_kind not in normalized_items:
                normalized_items.append(consumer_kind)

        if not normalized_items:
            raise ValueError("enabled_consumer_kinds 不能为空")
        return tuple(normalized_items)


class BackendWorkerSettings(BaseSettings):
    """描述 backend-worker 启动阶段使用的统一配置。

    字段：
    - app：worker 进程基础配置。
    - workspace：worker 工作目录配置。
    - database：数据库连接配置。
    - dataset_storage：数据集文件存储配置。
    - queue：本地任务队列配置。
    - task_manager：后台任务管理器配置。
    - deployment_process_supervisor：YOLOX async deployment 监督器配置。
    """

    model_config = SettingsConfigDict(
        env_prefix="AMVISION_WORKER_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app: BackendWorkerAppSettings = Field(default_factory=BackendWorkerAppSettings)
    workspace: BackendWorkerWorkspaceConfig = Field(
        default_factory=BackendWorkerWorkspaceConfig
    )
    database: BackendWorkerDatabaseConfig = Field(default_factory=BackendWorkerDatabaseConfig)
    dataset_storage: BackendWorkerDatasetStorageConfig = Field(
        default_factory=BackendWorkerDatasetStorageConfig
    )
    queue: BackendWorkerQueueConfig = Field(default_factory=BackendWorkerQueueConfig)
    task_manager: BackendWorkerTaskManagerConfig = Field(
        default_factory=BackendWorkerTaskManagerConfig
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
        """定义 worker 配置的加载优先级。

        参数：
        - settings_cls：当前 Settings 类型。
        - init_settings：显式传入构造参数的配置源。
        - env_settings：环境变量配置源。
        - dotenv_settings：dotenv 配置源。
        - file_secret_settings：file secret 配置源。

        返回：
        - 按优先级排列的配置源元组。
        """

        return (
            init_settings,
            env_settings,
            *build_json_config_sources(
                settings_cls,
                (
                    BACKEND_WORKER_LOCAL_CONFIG_FILE,
                    BACKEND_WORKER_CONFIG_FILE,
                ),
            ),
            dotenv_settings,
            file_secret_settings,
        )

    def resolve_workspace_dir(self) -> Path:
        """把 worker 工作目录转换为绝对路径。

        返回：
        - 当前 worker 使用的工作目录绝对路径。
        """

        return Path(self.workspace.root_dir).resolve()

    def to_database_settings(self) -> DatabaseSettings:
        """把统一配置转换为数据库连接配置。"""

        return DatabaseSettings(url=self.database.url, echo=self.database.echo)

    def to_dataset_storage_settings(self) -> DatasetStorageSettings:
        """把统一配置转换为本地数据集文件存储配置。"""

        return DatasetStorageSettings(root_dir=self.dataset_storage.root_dir)

    def to_queue_settings(self) -> LocalFileQueueSettings:
        """把统一配置转换为本地任务队列配置。"""

        return LocalFileQueueSettings(root_dir=self.queue.root_dir)


@lru_cache
def get_backend_worker_settings() -> BackendWorkerSettings:
    """读取并缓存 backend-worker 的统一配置。

    返回：
    - 当前进程共享的 BackendWorkerSettings。
    """

    return BackendWorkerSettings()