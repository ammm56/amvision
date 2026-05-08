"""backend-service 启动编排。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI

from backend.bootstrap.core import BootstrapStep, RuntimeBootstrap
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.nodes.node_pack_loader import NodePackLoader
from backend.queue import LocalFileQueueBackend
from backend.service.api.seeders import BackendServiceSeeder, BackendServiceSeederRunner
from backend.service.application.models.pretrained_catalog import YoloXPretrainedModelCatalogSeeder
from backend.service.application.workflows.graph_executor import WorkflowNodeRuntimeRegistry
from backend.service.application.workflows.runtime_worker import WorkflowRuntimeWorkerManager
from backend.service.application.workflows.service_node_runtime import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.settings import BackendServiceSettings, get_backend_service_settings
from backend.workers.task_manager import HostedBackgroundTaskManager


@dataclass(frozen=True)
class BackendServiceRuntime:
    """描述 backend-service 启动后持有的基础运行时资源。

    字段：
    - settings：当前 backend-service 进程使用的统一配置。
    - session_factory：数据库会话工厂。
    - dataset_storage：本地数据集文件存储服务。
    - queue_backend：本地任务队列后端。
    - node_pack_loader：节点包目录加载器。
    - node_catalog_registry：统一节点目录注册表。
    - workflow_node_runtime_registry_loader：workflow 节点运行时注册表加载器。
    - workflow_node_runtime_registry：workflow 节点运行时注册表。
    - workflow_service_node_runtime_context：workflow service nodes 使用的进程级上下文。
    - yolox_sync_deployment_process_supervisor：同步 YOLOX deployment 进程监督器。
    - yolox_async_deployment_process_supervisor：异步 YOLOX deployment 进程监督器。
    - workflow_runtime_worker_manager：workflow runtime worker 管理器。
    - background_task_manager_host：当前进程托管的后台任务管理器宿主。
    """

    settings: BackendServiceSettings
    session_factory: SessionFactory
    dataset_storage: LocalDatasetStorage
    queue_backend: LocalFileQueueBackend
    node_pack_loader: NodePackLoader
    node_catalog_registry: NodeCatalogRegistry
    workflow_node_runtime_registry_loader: WorkflowNodeRuntimeRegistryLoader
    workflow_node_runtime_registry: WorkflowNodeRuntimeRegistry
    workflow_service_node_runtime_context: WorkflowServiceNodeRuntimeContext
    yolox_sync_deployment_process_supervisor: YoloXDeploymentProcessSupervisor
    yolox_async_deployment_process_supervisor: YoloXDeploymentProcessSupervisor
    workflow_runtime_worker_manager: WorkflowRuntimeWorkerManager
    background_task_manager_host: HostedBackgroundTaskManager | None


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


class LoadBackendServiceNodeCatalogStep:
    """加载 backend-service 节点目录元数据的步骤。"""

    def get_step_name(self) -> str:
        """返回当前步骤名称。

        返回：
        - 当前步骤的稳定名称。
        """

        return "load-service-node-catalog"

    def run(self, runtime: BackendServiceRuntime) -> None:
        """执行 backend-service 节点目录元数据准备步骤。

        参数：
        - runtime：当前应用实例使用的运行时资源。

        说明：
        - 当前阶段把自定义节点包发现和 workflow 节点目录扫描收敛到 NodePackLoader。
        - 当前步骤同时执行 node pack entrypoint 到 runtime handler 的注册。
        - 后续节点包 capability 索引、启停状态和版本管理继续在这里扩展。
        """

        runtime.node_pack_loader.refresh()
        runtime.workflow_node_runtime_registry_loader.refresh()


class BackendServiceBootstrap(RuntimeBootstrap[BackendServiceSettings, BackendServiceRuntime]):
    """按固定步骤准备 backend-service 运行环境。"""

    def __init__(
        self,
        *,
        settings: BackendServiceSettings | None = None,
        session_factory: SessionFactory | None = None,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: LocalFileQueueBackend | None = None,
        seeders: tuple[BackendServiceSeeder, ...] | None = None,
    ) -> None:
        """初始化启动编排器。

        参数：
        - settings：可选的统一配置对象。
        - session_factory：可选的数据库会话工厂。
        - dataset_storage：可选的数据集本地文件存储服务。
        - queue_backend：可选的本地任务队列后端。
        - seeders：可选的启动期 seeder 列表。
        """

        self._provided_settings = settings
        self._provided_session_factory = session_factory
        self._provided_dataset_storage = dataset_storage
        self._provided_queue_backend = queue_backend
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

        session_factory = self._provided_session_factory or SessionFactory(
            settings.to_database_settings()
        )
        dataset_storage = self._provided_dataset_storage or LocalDatasetStorage(
            settings.to_dataset_storage_settings()
        )
        queue_backend = self._provided_queue_backend or LocalFileQueueBackend(
            settings.to_queue_settings()
        )
        node_pack_loader = LocalNodePackLoader(settings.custom_nodes.root_dir)
        node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
        workflow_node_runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
            node_catalog_registry=node_catalog_registry,
            node_pack_loader=node_pack_loader,
        )
        yolox_sync_deployment_process_supervisor = YoloXDeploymentProcessSupervisor(
            dataset_storage_root_dir=str(dataset_storage.root_dir),
            runtime_mode="sync",
            settings=settings.deployment_process_supervisor,
        )
        yolox_async_deployment_process_supervisor = YoloXDeploymentProcessSupervisor(
            dataset_storage_root_dir=str(dataset_storage.root_dir),
            runtime_mode="async",
            settings=settings.deployment_process_supervisor,
        )
        background_task_manager_host = self._build_background_task_manager_host(
            settings=settings,
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
            yolox_async_deployment_process_supervisor=yolox_async_deployment_process_supervisor,
        )
        workflow_service_node_runtime_context = WorkflowServiceNodeRuntimeContext(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
            yolox_sync_deployment_process_supervisor=yolox_sync_deployment_process_supervisor,
            yolox_async_deployment_process_supervisor=yolox_async_deployment_process_supervisor,
        )
        workflow_runtime_worker_manager = WorkflowRuntimeWorkerManager(settings=settings)
        return BackendServiceRuntime(
            settings=settings,
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
            node_pack_loader=node_pack_loader,
            node_catalog_registry=node_catalog_registry,
            workflow_node_runtime_registry_loader=workflow_node_runtime_registry_loader,
            workflow_node_runtime_registry=workflow_node_runtime_registry_loader.get_runtime_registry(),
            workflow_service_node_runtime_context=workflow_service_node_runtime_context,
            yolox_sync_deployment_process_supervisor=yolox_sync_deployment_process_supervisor,
            yolox_async_deployment_process_supervisor=yolox_async_deployment_process_supervisor,
            workflow_runtime_worker_manager=workflow_runtime_worker_manager,
            background_task_manager_host=background_task_manager_host,
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
        application.state.queue_backend = runtime.queue_backend
        application.state.node_pack_loader = runtime.node_pack_loader
        application.state.node_catalog_registry = runtime.node_catalog_registry
        application.state.workflow_node_runtime_registry_loader = runtime.workflow_node_runtime_registry_loader
        application.state.workflow_node_runtime_registry = runtime.workflow_node_runtime_registry
        application.state.workflow_service_node_runtime_context = runtime.workflow_service_node_runtime_context
        application.state.yolox_sync_deployment_process_supervisor = runtime.yolox_sync_deployment_process_supervisor
        application.state.yolox_async_deployment_process_supervisor = runtime.yolox_async_deployment_process_supervisor
        application.state.workflow_runtime_worker_manager = runtime.workflow_runtime_worker_manager
        application.state.background_task_manager_host = runtime.background_task_manager_host

    def start_runtime(self, runtime: BackendServiceRuntime) -> None:
        """启动 backend-service 托管的长生命周期资源。

        参数：
        - runtime：当前应用实例使用的运行时资源。
        """

        runtime.yolox_sync_deployment_process_supervisor.start()
        runtime.yolox_async_deployment_process_supervisor.start()
        runtime.workflow_runtime_worker_manager.start()
        if runtime.background_task_manager_host is not None:
            runtime.background_task_manager_host.start()

    def stop_runtime(self, runtime: BackendServiceRuntime) -> None:
        """停止 backend-service 托管的长生命周期资源。

        参数：
        - runtime：当前应用实例使用的运行时资源。
        """

        if runtime.background_task_manager_host is not None:
            runtime.background_task_manager_host.stop()
        runtime.workflow_runtime_worker_manager.stop()
        runtime.yolox_sync_deployment_process_supervisor.stop()
        runtime.yolox_async_deployment_process_supervisor.stop()
        runtime.session_factory.engine.dispose()

    def _build_steps(self) -> tuple[BootstrapStep[BackendServiceRuntime], ...]:
        """返回当前 backend-service 启动链要执行的步骤元组。

        返回：
        - 当前 backend-service 启动链的步骤元组。

        说明：
        - 配置加载是 bootstrap 的第一步，在 build_runtime 之前完成。
        - 当前服务进程只执行适合 backend-service 的轻量启动步骤。
        - 当前启动顺序为：数据库 -> seeders -> 节点目录元数据。
        """

        return (
            InitializeDatabaseSchemaStep(),
            RunBackendServiceSeedersStep(self._build_seeders()),
            LoadBackendServiceNodeCatalogStep(),
        )

    def _build_seeders(self) -> tuple[BackendServiceSeeder, ...]:
        """返回当前 backend-service 启动流程要执行的 seeders。

        返回：
        - 当前启动流程使用的 seeder 元组。
        """

        default_seeders: tuple[BackendServiceSeeder, ...] = (YoloXPretrainedModelCatalogSeeder(),)
        if self._provided_seeders is None:
            return default_seeders

        return default_seeders + self._provided_seeders

    def _build_background_task_manager_host(
        self,
        *,
        settings: BackendServiceSettings,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: LocalFileQueueBackend,
        yolox_async_deployment_process_supervisor: YoloXDeploymentProcessSupervisor,
    ) -> HostedBackgroundTaskManager | None:
        """按 backend-service 配置创建后台任务管理器宿主。

        参数：
        - settings：当前 backend-service 统一配置。
        - session_factory：数据库会话工厂。
        - dataset_storage：本地数据集文件存储服务。
        - queue_backend：本地任务队列后端。

        返回：
        - 已配置完成的后台任务管理器宿主；未启用时返回 None。
        """

        _ = (
            settings,
            session_factory,
            dataset_storage,
            queue_backend,
            yolox_async_deployment_process_supervisor,
        )
        return None