"""backend-maintenance 启动编排。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.bootstrap.core import BootstrapStep, RuntimeBootstrap
from backend.maintenance.settings import (
    BackendMaintenanceSettings,
    get_backend_maintenance_settings,
)


@dataclass(frozen=True)
class BackendMaintenanceRuntime:
    """描述 backend-maintenance 启动后持有的基础运行时资源。

    字段：
    - settings：当前 maintenance 进程使用的统一配置。
    - workspace_dir：maintenance 运行态工作目录。
    """

    settings: BackendMaintenanceSettings
    workspace_dir: Path


class PrepareBackendMaintenanceWorkspaceStep:
    """准备 backend-maintenance 本地工作目录。"""

    def get_step_name(self) -> str:
        """返回当前步骤名称。

        返回：
        - 当前步骤的稳定名称。
        """

        return "prepare-maintenance-workspace"

    def run(self, runtime: BackendMaintenanceRuntime) -> None:
        """创建 maintenance 运行所需的本地目录。

        参数：
        - runtime：当前 maintenance 进程使用的运行时资源。
        """

        runtime.workspace_dir.mkdir(parents=True, exist_ok=True)


class LoadBackendMaintenanceOperationCatalogStep:
    """加载 backend-maintenance 启动期需要的运维操作目录。"""

    def get_step_name(self) -> str:
        """返回当前步骤名称。

        返回：
        - 当前步骤的稳定名称。
        """

        return "load-maintenance-operation-catalog"

    def run(self, runtime: BackendMaintenanceRuntime) -> None:
        """执行 maintenance 运维操作目录准备步骤。

        参数：
        - runtime：当前 maintenance 进程使用的运行时资源。

        说明：
        - 当前仓库还没有正式接入 maintenance 命令或修复任务索引。
        - 后续数据库修复、文件修复和缓存清理等操作目录可放在这里。
        """

        _ = runtime


class BackendMaintenanceBootstrap(
    RuntimeBootstrap[BackendMaintenanceSettings, BackendMaintenanceRuntime]
):
    """按固定步骤准备 backend-maintenance 运行环境。"""

    def __init__(
        self,
        *,
        settings: BackendMaintenanceSettings | None = None,
        workspace_dir: Path | None = None,
    ) -> None:
        """初始化 maintenance 启动编排器。

        参数：
        - settings：可选的统一配置对象。
        - workspace_dir：可选的工作目录覆盖路径。
        """

        self._provided_settings = settings
        self._provided_workspace_dir = workspace_dir

    def load_settings(self) -> BackendMaintenanceSettings:
        """读取 backend-maintenance 的统一配置。

        返回：
        - 当前启动流程使用的 BackendMaintenanceSettings。
        """

        return self._provided_settings or get_backend_maintenance_settings()

    def build_runtime(
        self,
        settings: BackendMaintenanceSettings,
    ) -> BackendMaintenanceRuntime:
        """根据统一配置解析 maintenance 的基础运行时资源。

        参数：
        - settings：当前启动流程使用的统一配置。

        返回：
        - 当前 maintenance 进程要绑定的运行时资源。
        """

        workspace_dir = (
            self._provided_workspace_dir.resolve()
            if self._provided_workspace_dir is not None
            else settings.resolve_workspace_dir()
        )
        return BackendMaintenanceRuntime(
            settings=settings,
            workspace_dir=workspace_dir,
        )

    def _build_steps(self) -> tuple[BootstrapStep[BackendMaintenanceRuntime], ...]:
        """返回当前 maintenance 启动链要执行的步骤元组。

        返回：
        - 当前 maintenance 启动链的步骤元组。
        """

        return (
            PrepareBackendMaintenanceWorkspaceStep(),
            LoadBackendMaintenanceOperationCatalogStep(),
        )