"""backend-worker 启动编排。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.bootstrap.core import BootstrapStep, RuntimeBootstrap
from backend.queue import LocalFileQueueBackend
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.settings import BackendWorkerSettings, get_backend_worker_settings


@dataclass(frozen=True)
class BackendWorkerRuntime:
    """描述 backend-worker 启动后持有的基础运行时资源。

    字段：
    - settings：当前 worker 进程使用的统一配置。
    - workspace_dir：worker 运行态工作目录。
    - session_factory：数据库会话工厂。
    - dataset_storage：本地数据集文件存储服务。
    - queue_backend：本地任务队列后端。
    - yolox_async_deployment_process_supervisor：YOLOX async deployment 进程监督器。
    """

    settings: BackendWorkerSettings
    workspace_dir: Path
    session_factory: SessionFactory
    dataset_storage: LocalDatasetStorage
    queue_backend: LocalFileQueueBackend
    yolox_async_deployment_process_supervisor: YoloXDeploymentProcessSupervisor


class PrepareBackendWorkerWorkspaceStep:
    """准备 backend-worker 本地工作目录。"""

    def get_step_name(self) -> str:
        """返回当前步骤名称。

        返回：
        - 当前步骤的稳定名称。
        """

        return "prepare-worker-workspace"

    def run(self, runtime: BackendWorkerRuntime) -> None:
        """创建 worker 运行所需的本地目录。

        参数：
        - runtime：当前 worker 进程使用的运行时资源。
        """

        runtime.workspace_dir.mkdir(parents=True, exist_ok=True)


class LoadBackendWorkerNodeCatalogStep:
    """加载 backend-worker 启动期需要的节点目录元数据。"""

    def get_step_name(self) -> str:
        """返回当前步骤名称。

        返回：
        - 当前步骤的稳定名称。
        """

        return "load-worker-node-catalog"

    def run(self, runtime: BackendWorkerRuntime) -> None:
        """执行 worker 节点目录元数据准备步骤。

        参数：
        - runtime：当前 worker 进程使用的运行时资源。

        说明：
        - 当前仓库还没有正式接入 worker 侧 NodePackLoader。
        - 后续模型运行时、转换 backend 和自定义节点索引可放在这里。
        """

        _ = runtime


class BackendWorkerBootstrap(RuntimeBootstrap[BackendWorkerSettings, BackendWorkerRuntime]):
    """按固定步骤准备 backend-worker 运行环境。"""

    def __init__(
        self,
        *,
        settings: BackendWorkerSettings | None = None,
        workspace_dir: Path | None = None,
    ) -> None:
        """初始化 worker 启动编排器。

        参数：
        - settings：可选的统一配置对象。
        - workspace_dir：可选的工作目录覆盖路径。
        """

        self._provided_settings = settings
        self._provided_workspace_dir = workspace_dir

    def load_settings(self) -> BackendWorkerSettings:
        """读取 backend-worker 的统一配置。

        返回：
        - 当前启动流程使用的 BackendWorkerSettings。
        """

        return self._provided_settings or get_backend_worker_settings()

    def build_runtime(self, settings: BackendWorkerSettings) -> BackendWorkerRuntime:
        """根据统一配置解析 worker 的基础运行时资源。

        参数：
        - settings：当前启动流程使用的统一配置。

        返回：
        - 当前 worker 进程要绑定的运行时资源。
        """

        workspace_dir = (
            self._provided_workspace_dir.resolve()
            if self._provided_workspace_dir is not None
            else settings.resolve_workspace_dir()
        )
        session_factory = SessionFactory(settings.to_database_settings())
        dataset_storage = LocalDatasetStorage(settings.to_dataset_storage_settings())
        queue_backend = LocalFileQueueBackend(settings.to_queue_settings())
        return BackendWorkerRuntime(
            settings=settings,
            workspace_dir=workspace_dir,
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
            yolox_async_deployment_process_supervisor=YoloXDeploymentProcessSupervisor(
                dataset_storage_root_dir=str(dataset_storage.root_dir),
                runtime_mode="async",
                settings=settings.deployment_process_supervisor,
            ),
        )

    def _build_steps(self) -> tuple[BootstrapStep[BackendWorkerRuntime], ...]:
        """返回当前 worker 启动链要执行的步骤元组。

        返回：
        - 当前 worker 启动链的步骤元组。
        """

        return (
            PrepareBackendWorkerWorkspaceStep(),
            LoadBackendWorkerNodeCatalogStep(),
        )