"""backend-worker 统一配置定义。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from backend.bootstrap.settings import build_json_config_sources
from backend.service.application.runtime.device_leases import (
    DeviceLeaseProviderConfig,
)
from backend.service.infrastructure.db.session import DatabaseSettings
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
)
from backend.service.infrastructure.queue.local_file import LocalFileQueueSettings
from backend.version import BACKEND_VERSION

CONFIG_DIR = Path("config")
BACKEND_WORKER_CONFIG_FILE = CONFIG_DIR / "backend-worker.json"
BACKEND_WORKER_LOCAL_CONFIG_FILE = CONFIG_DIR / "backend-worker.local.json"

BACKEND_WORKER_CONSUMER_DATASET_IMPORT = "dataset-import"
BACKEND_WORKER_CONSUMER_DATASET_EXPORT = "dataset-export"
BACKEND_WORKER_CONSUMER_YOLOX_TRAINING = "yolox-training"
BACKEND_WORKER_CONSUMER_YOLOV8_TRAINING = "yolov8-training"
BACKEND_WORKER_CONSUMER_YOLO11_TRAINING = "yolo11-training"
BACKEND_WORKER_CONSUMER_YOLO26_TRAINING = "yolo26-training"
BACKEND_WORKER_CONSUMER_YOLOX_CONVERSION = "yolox-conversion"
BACKEND_WORKER_CONSUMER_YOLOV8_CONVERSION = "yolov8-conversion"
BACKEND_WORKER_CONSUMER_YOLO11_CONVERSION = "yolo11-conversion"
BACKEND_WORKER_CONSUMER_YOLO26_CONVERSION = "yolo26-conversion"
BACKEND_WORKER_CONSUMER_DETECTION_INFERENCE = "detection-inference"
BACKEND_WORKER_CONSUMER_CLASSIFICATION_INFERENCE = "classification-inference"
BACKEND_WORKER_CONSUMER_SEGMENTATION_INFERENCE = "segmentation-inference"
BACKEND_WORKER_CONSUMER_POSE_INFERENCE = "pose-inference"
BACKEND_WORKER_CONSUMER_OBB_INFERENCE = "obb-inference"
BACKEND_WORKER_CONSUMER_CLASSIFICATION_TRAINING = "classification-training"
BACKEND_WORKER_CONSUMER_SEGMENTATION_TRAINING = "segmentation-training"
BACKEND_WORKER_CONSUMER_POSE_TRAINING = "pose-training"
BACKEND_WORKER_CONSUMER_OBB_TRAINING = "obb-training"
BACKEND_WORKER_CONSUMER_RFDETR_TRAINING = "rfdetr-training"
BACKEND_WORKER_CONSUMER_RFDETR_CONVERSION = "rfdetr-conversion"
BACKEND_WORKER_CONSUMER_CLASSIFICATION_EVALUATION = "classification-evaluation"
BACKEND_WORKER_CONSUMER_SEGMENTATION_EVALUATION = "segmentation-evaluation"
BACKEND_WORKER_CONSUMER_DETECTION_EVALUATION = "detection-evaluation"
BACKEND_WORKER_CONSUMER_POSE_EVALUATION = "pose-evaluation"
BACKEND_WORKER_CONSUMER_OBB_EVALUATION = "obb-evaluation"
SUPPORTED_BACKEND_WORKER_CONSUMER_KINDS = frozenset(
    (
        BACKEND_WORKER_CONSUMER_DATASET_IMPORT,
        BACKEND_WORKER_CONSUMER_DATASET_EXPORT,
        BACKEND_WORKER_CONSUMER_YOLOX_TRAINING,
        BACKEND_WORKER_CONSUMER_YOLOV8_TRAINING,
        BACKEND_WORKER_CONSUMER_YOLO11_TRAINING,
        BACKEND_WORKER_CONSUMER_YOLO26_TRAINING,
        BACKEND_WORKER_CONSUMER_YOLOX_CONVERSION,
        BACKEND_WORKER_CONSUMER_YOLOV8_CONVERSION,
        BACKEND_WORKER_CONSUMER_YOLO11_CONVERSION,
        BACKEND_WORKER_CONSUMER_YOLO26_CONVERSION,
        BACKEND_WORKER_CONSUMER_CLASSIFICATION_EVALUATION,
        BACKEND_WORKER_CONSUMER_SEGMENTATION_EVALUATION,
        BACKEND_WORKER_CONSUMER_DETECTION_EVALUATION,
        BACKEND_WORKER_CONSUMER_POSE_EVALUATION,
        BACKEND_WORKER_CONSUMER_OBB_EVALUATION,
        BACKEND_WORKER_CONSUMER_RFDETR_CONVERSION,
        BACKEND_WORKER_CONSUMER_DETECTION_INFERENCE,
        BACKEND_WORKER_CONSUMER_CLASSIFICATION_INFERENCE,
        BACKEND_WORKER_CONSUMER_SEGMENTATION_INFERENCE,
        BACKEND_WORKER_CONSUMER_POSE_INFERENCE,
        BACKEND_WORKER_CONSUMER_OBB_INFERENCE,
        BACKEND_WORKER_CONSUMER_CLASSIFICATION_TRAINING,
        BACKEND_WORKER_CONSUMER_SEGMENTATION_TRAINING,
        BACKEND_WORKER_CONSUMER_POSE_TRAINING,
        BACKEND_WORKER_CONSUMER_OBB_TRAINING,
        BACKEND_WORKER_CONSUMER_RFDETR_TRAINING,
    )
)


class BackendWorkerAppSettings(BaseModel):
    """描述 backend-worker 进程自身的基础配置。

    字段：
    - app_name：worker 进程名称。
    - app_version：worker 进程版本号。
    """

    app_name: str = "amvision worker"
    app_version: str = BACKEND_VERSION


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
    max_import_package_bytes: int = Field(default=20 * 1024**3, gt=0)
    max_import_extracted_bytes: int = Field(default=200 * 1024**3, gt=0)
    max_import_member_count: int = Field(default=2_000_000, gt=0)
    max_import_compression_ratio: float = Field(default=1000.0, gt=0)
    max_import_metadata_file_bytes: int = Field(default=256 * 1024**2, gt=0)
    max_import_label_file_bytes: int = Field(default=16 * 1024**2, gt=0)
    max_import_sample_count: int = Field(default=100_000, gt=0)
    max_import_annotation_count: int = Field(default=1_000_000, gt=0)


class BackendWorkerQueueConfig(BaseModel):
    """描述 backend-worker 使用的本地队列配置。

    字段：
    - root_dir：队列根目录。
    - lease_timeout_seconds：普通任务 leased 文件的默认恢复超时秒数。
    - completed_retention_seconds：completed 任务文件保留秒数。
    - failed_retention_seconds：failed 任务文件保留秒数。
    - response_queue_retention_seconds：一次性响应队列目录保留秒数。
    - file_operation_retry_timeout_seconds：Windows 文件短暂占用的重试预算秒数。
    """

    root_dir: str = "./data/queue"
    lease_timeout_seconds: float = 86400.0
    completed_retention_seconds: float = 86400.0
    failed_retention_seconds: float = 604800.0
    response_queue_retention_seconds: float = 3600.0
    file_operation_retry_timeout_seconds: float = Field(default=2.0, ge=0)


class BackendWorkerTrainingTelemetryConfig(BaseModel):
    """描述 worker 写入本机 mmap 训练遥测 ring 的参数。"""

    enabled: bool = True
    root_dir: str = "./data/runtime/training-telemetry"
    slot_count: int = Field(default=512, gt=0)
    payload_capacity_bytes: int = Field(default=16 * 1024, ge=1024)
    min_publish_interval_seconds: float = Field(default=0.1, ge=0)


class BackendWorkerConversionConfig(BaseModel):
    """描述 conversion helper 上限、停止和发布恢复参数。"""

    helper_timeout_seconds: float = Field(default=7200.0, gt=0)
    termination_grace_seconds: float = Field(default=15.0, ge=0)
    publication_orphan_grace_seconds: float = Field(default=3600.0, ge=0)


class BackendWorkerSettings(BaseSettings):
    """描述 backend-worker 启动阶段使用的统一配置。

    字段：
    - app：worker 进程基础配置。
    - workspace：worker 工作目录配置。
    - database：数据库连接配置。
    - dataset_storage：数据集文件存储配置。
    - queue：本地任务队列配置。
    - conversion：conversion attempt 进程树和发布恢复配置。
    - device_leases：Training/CUDA Conversion 跨进程独占设备 lease 配置。
    - Profile Manifest：消费者集合、并发数和轮询间隔的唯一配置来源。
    - async_inference_gateway_request_timeout_seconds：等待 backend-service async inference gateway 响应的最长秒数。
    """

    model_config = SettingsConfigDict(
        env_prefix="AMVISION_WORKER_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    app: BackendWorkerAppSettings = Field(default_factory=BackendWorkerAppSettings)
    workspace: BackendWorkerWorkspaceConfig = Field(
        default_factory=BackendWorkerWorkspaceConfig
    )
    database: BackendWorkerDatabaseConfig = Field(
        default_factory=BackendWorkerDatabaseConfig
    )
    dataset_storage: BackendWorkerDatasetStorageConfig = Field(
        default_factory=BackendWorkerDatasetStorageConfig
    )
    queue: BackendWorkerQueueConfig = Field(default_factory=BackendWorkerQueueConfig)
    training_telemetry: BackendWorkerTrainingTelemetryConfig = Field(
        default_factory=BackendWorkerTrainingTelemetryConfig
    )
    conversion: BackendWorkerConversionConfig = Field(
        default_factory=BackendWorkerConversionConfig
    )
    device_leases: DeviceLeaseProviderConfig = Field(
        default_factory=DeviceLeaseProviderConfig
    )
    async_inference_gateway_request_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
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

        return DatasetStorageSettings(
            root_dir=self.dataset_storage.root_dir,
            max_import_package_bytes=self.dataset_storage.max_import_package_bytes,
            max_import_extracted_bytes=self.dataset_storage.max_import_extracted_bytes,
            max_import_member_count=self.dataset_storage.max_import_member_count,
            max_import_compression_ratio=self.dataset_storage.max_import_compression_ratio,
            max_import_metadata_file_bytes=self.dataset_storage.max_import_metadata_file_bytes,
            max_import_label_file_bytes=self.dataset_storage.max_import_label_file_bytes,
            max_import_sample_count=self.dataset_storage.max_import_sample_count,
            max_import_annotation_count=self.dataset_storage.max_import_annotation_count,
        )

    def to_queue_settings(self) -> LocalFileQueueSettings:
        """把统一配置转换为本地任务队列配置。"""

        return LocalFileQueueSettings(
            root_dir=self.queue.root_dir,
            lease_timeout_seconds=self.queue.lease_timeout_seconds,
            completed_retention_seconds=self.queue.completed_retention_seconds,
            failed_retention_seconds=self.queue.failed_retention_seconds,
            response_queue_retention_seconds=self.queue.response_queue_retention_seconds,
            file_operation_retry_timeout_seconds=(
                self.queue.file_operation_retry_timeout_seconds
            ),
        )


@lru_cache
def get_backend_worker_settings() -> BackendWorkerSettings:
    """读取并缓存 backend-worker 的统一配置。

    返回：
    - 当前进程共享的 BackendWorkerSettings。
    """

    return BackendWorkerSettings()
