"""backend-maintenance 统一配置定义。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from backend.bootstrap.settings import build_json_config_sources


CONFIG_DIR = Path("config")
BACKEND_MAINTENANCE_CONFIG_FILE = CONFIG_DIR / "backend-maintenance.json"
BACKEND_MAINTENANCE_LOCAL_CONFIG_FILE = CONFIG_DIR / "backend-maintenance.local.json"


class BackendMaintenanceAppSettings(BaseModel):
    """描述 backend-maintenance 进程自身的基础配置。

    字段：
    - app_name：maintenance 进程名称。
    - app_version：maintenance 进程版本号。
    """

    app_name: str = "amvision maintenance"
    app_version: str = "0.1.0"


class BackendMaintenanceWorkspaceConfig(BaseModel):
    """描述 backend-maintenance 使用的工作目录配置。

    字段：
    - root_dir：maintenance 运行态文件根目录。
    """

    root_dir: str = "./data/maintenance"


class BackendMaintenanceSettings(BaseSettings):
    """描述 backend-maintenance 启动阶段使用的统一配置。

    字段：
    - app：maintenance 进程基础配置。
    - workspace：maintenance 工作目录配置。
    """

    model_config = SettingsConfigDict(
        env_prefix="AMVISION_MAINTENANCE_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app: BackendMaintenanceAppSettings = Field(default_factory=BackendMaintenanceAppSettings)
    workspace: BackendMaintenanceWorkspaceConfig = Field(
        default_factory=BackendMaintenanceWorkspaceConfig
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
        """定义 maintenance 配置的加载优先级。

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
                    BACKEND_MAINTENANCE_LOCAL_CONFIG_FILE,
                    BACKEND_MAINTENANCE_CONFIG_FILE,
                ),
            ),
            dotenv_settings,
            file_secret_settings,
        )

    def resolve_workspace_dir(self) -> Path:
        """把 maintenance 工作目录转换为绝对路径。

        返回：
        - 当前 maintenance 使用的工作目录绝对路径。
        """

        return Path(self.workspace.root_dir).resolve()


@lru_cache
def get_backend_maintenance_settings() -> BackendMaintenanceSettings:
    """读取并缓存 backend-maintenance 的统一配置。

    返回：
    - 当前进程共享的 BackendMaintenanceSettings。
    """

    return BackendMaintenanceSettings()