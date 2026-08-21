"""独立 inference daemon 的运行资源和生命周期。"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
import logging

from backend.queue import LocalFileQueueBackend
from backend.service.application.deployments.classification_deployment_service import (
    SqlAlchemyClassificationDeploymentService,
)
from backend.service.application.deployments.detection_deployment_service import (
    SqlAlchemyDetectionDeploymentService,
)
from backend.service.application.deployments.deployment_instance_service import (
    SqlAlchemyDeploymentInstanceService,
)
from backend.service.application.deployments.obb_deployment_service import (
    SqlAlchemyObbDeploymentService,
)
from backend.service.application.deployments.pose_deployment_service import (
    SqlAlchemyPoseDeploymentService,
)
from backend.service.application.deployments.segmentation_deployment_service import (
    SqlAlchemySegmentationDeploymentService,
)
from backend.service.application.events import InMemoryServiceEventBus
from backend.service.application.local_buffers import LocalBufferBrokerProcessSupervisor
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.application.runtime.deployment.deployment_runtime_reconciler import (
    DeploymentRuntimeBinding,
    DeploymentRuntimeReconciler,
)
from backend.service.application.runtime.deployment.deployment_runtime_state_service import (
    DeploymentRuntimeStateService,
)
from backend.service.application.runtime.deployment.inference_control import (
    InferenceControlBinding,
    InferenceControlDispatcher,
)
from backend.service.application.runtime.deployment.inference_local_mmap import (
    InferenceLocalMmapServer,
    build_inference_local_mmap_path,
)
from backend.service.application.runtime.deployment.runtime_factory import (
    build_task_type_deployment_runtimes,
)
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.settings import BackendServiceSettings


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class InferenceDaemonTaskRuntime:
    """描述 daemon 中一个 task type 的运行组件。"""

    task_type: str
    deployment_service: SqlAlchemyDeploymentInstanceService
    sync_supervisor: DeploymentProcessSupervisor
    async_supervisor: DeploymentProcessSupervisor
    async_gateway_registry: object


@dataclass(frozen=True)
class InferenceDaemonRuntime:
    """描述独立 inference daemon 持有的全部资源。"""

    settings: BackendServiceSettings
    session_factory: SessionFactory
    dataset_storage: LocalDatasetStorage
    queue_backend: LocalFileQueueBackend
    async_local_buffer_broker_supervisor: LocalBufferBrokerProcessSupervisor
    task_runtimes: tuple[InferenceDaemonTaskRuntime, ...]
    deployment_runtime_reconciler: DeploymentRuntimeReconciler
    control_dispatcher: InferenceControlDispatcher
    local_mmap_server: InferenceLocalMmapServer | None

    def start(self) -> None:
        """按依赖顺序启动 supervisor、gateway、恢复协调器和控制面。

        backend 主 LocalBufferBroker 仍由 backend-service 负责。daemon 私有 broker
        只把持久异步任务的 ObjectStore 图片暂存为短期 BufferRef；同步请求继续
        直接读取 backend 主池。模型子进程在两条链路上都只接收 LocalBuffer 引用。
        """

        started_components: list[object] = []
        try:
            self.async_local_buffer_broker_supervisor.start()
            started_components.append(self.async_local_buffer_broker_supervisor)
            for task_runtime in self.task_runtimes:
                for component in (
                    task_runtime.sync_supervisor,
                    task_runtime.async_supervisor,
                    task_runtime.async_gateway_registry,
                ):
                    component.start()
                    started_components.append(component)
            self.deployment_runtime_reconciler.start()
            started_components.append(self.deployment_runtime_reconciler)
            self.control_dispatcher.start()
            started_components.append(self.control_dispatcher)
            if self.local_mmap_server is not None:
                self.local_mmap_server.start()
                started_components.append(self.local_mmap_server)
        except Exception:
            for component in reversed(started_components):
                with contextlib.suppress(Exception):
                    component.stop()
            raise

    def stop(self) -> None:
        """反序停止全部组件；单个组件失败不得跳过后续资源回收。"""

        components: list[object] = []
        if self.local_mmap_server is not None:
            components.append(self.local_mmap_server)
        components.extend((self.control_dispatcher, self.deployment_runtime_reconciler))
        for task_runtime in reversed(self.task_runtimes):
            components.extend(
                (
                    task_runtime.async_gateway_registry,
                    task_runtime.async_supervisor,
                    task_runtime.sync_supervisor,
                )
            )
        components.append(self.async_local_buffer_broker_supervisor)

        first_error: Exception | None = None
        for component in components:
            try:
                component.stop()
            except Exception as error:  # noqa: BLE001 - 停机必须继续回收其余组件
                if first_error is None:
                    first_error = error
                LOGGER.exception(
                    "停止 inference daemon 组件失败: component=%s",
                    type(component).__name__,
                )
        self.session_factory.engine.dispose()
        if first_error is not None:
            raise first_error


def build_inference_daemon_runtime(
    settings: BackendServiceSettings,
) -> InferenceDaemonRuntime:
    """从统一配置构建独立 inference daemon。"""

    session_factory = SessionFactory(settings.to_database_settings())
    initialize_database_schema(session_factory)
    service_event_bus = InMemoryServiceEventBus()
    session_factory.service_event_bus = service_event_bus
    dataset_storage = LocalDatasetStorage(settings.to_dataset_storage_settings())
    queue_backend = LocalFileQueueBackend(settings.to_queue_settings())
    async_local_buffer_broker_supervisor = LocalBufferBrokerProcessSupervisor(
        settings=settings.local_buffer_broker.model_copy(
            update={
                "root_dir": str(
                    Path(settings.local_buffer_broker.root_dir)
                    / "inference-daemon-private"
                )
            }
        )
    )
    build_kwargs = {
        "dataset_storage": dataset_storage,
        "service_event_bus": service_event_bus,
        "session_factory": session_factory,
        "local_buffer_broker_supervisor": async_local_buffer_broker_supervisor,
        "queue_backend": queue_backend,
        "async_inference_service_id": settings.async_inference_gateway.service_id,
        "settings": settings,
    }
    service_classes = {
        "detection": SqlAlchemyDetectionDeploymentService,
        "classification": SqlAlchemyClassificationDeploymentService,
        "segmentation": SqlAlchemySegmentationDeploymentService,
        "pose": SqlAlchemyPoseDeploymentService,
        "obb": SqlAlchemyObbDeploymentService,
    }
    task_runtimes: list[InferenceDaemonTaskRuntime] = []
    for task_type, service_class in service_classes.items():
        sync_supervisor, async_supervisor, async_gateway_registry = (
            build_task_type_deployment_runtimes(
                task_type=task_type,
                enable_direct_mmap_reader=True,
                **build_kwargs,
            )
        )
        task_runtimes.append(
            InferenceDaemonTaskRuntime(
                task_type=task_type,
                deployment_service=service_class(
                    session_factory=session_factory,
                    dataset_storage=dataset_storage,
                ),
                sync_supervisor=sync_supervisor,
                async_supervisor=async_supervisor,
                async_gateway_registry=async_gateway_registry,
            )
        )

    runtime_by_task_type = {item.task_type: item for item in task_runtimes}
    deployment_runtime_reconciler = DeploymentRuntimeReconciler(
        state_service=DeploymentRuntimeStateService(session_factory=session_factory),
        lookup_service=SqlAlchemyDeploymentInstanceService(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        ),
        bindings_by_task_type={
            task_type: DeploymentRuntimeBinding(
                deployment_service=item.deployment_service,
                sync_supervisor=item.sync_supervisor,
                async_supervisor=item.async_supervisor,
                async_gateway_registry=item.async_gateway_registry,
            )
            for task_type, item in runtime_by_task_type.items()
        },
        settings=settings.deployment_runtime_reconciler,
    )
    control_dispatcher = InferenceControlDispatcher(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        service_id=settings.inference_daemon.service_id,
        runtime_state_service=DeploymentRuntimeStateService(
            session_factory=session_factory
        ),
        bindings_by_task_type={
            task_type: InferenceControlBinding(
                sync_supervisor=item.sync_supervisor,
                async_supervisor=item.async_supervisor,
                async_gateway_registry=item.async_gateway_registry,
            )
            for task_type, item in runtime_by_task_type.items()
        },
        max_concurrent_requests=(
            settings.inference_daemon.control_max_concurrent_requests
        ),
        poll_interval_seconds=(settings.inference_daemon.control_poll_interval_seconds),
        lease_timeout_seconds=(settings.inference_daemon.control_lease_timeout_seconds),
        response_queue_retention_seconds=(
            settings.queue.response_queue_retention_seconds
        ),
    )
    local_mmap_server = (
        InferenceLocalMmapServer(
            path=build_inference_local_mmap_path(
                root_dir=settings.local_buffer_broker.root_dir,
                service_id=settings.inference_daemon.service_id,
            ),
            request_handler=control_dispatcher.handle_local_mmap_request,
            slot_count=settings.inference_daemon.mmap_mailbox.slot_count,
            slot_payload_capacity_bytes=(
                settings.inference_daemon.mmap_mailbox.message_capacity_bytes
            ),
            overflow_page_count=(
                settings.inference_daemon.mmap_mailbox.overflow_page_count
            ),
            overflow_page_capacity_bytes=(
                settings.inference_daemon.mmap_mailbox.overflow_page_capacity_bytes
            ),
            max_overflow_pages_per_response=(
                settings.inference_daemon.mmap_mailbox.max_overflow_pages_per_response
            ),
            compression_threshold_bytes=(
                settings.inference_daemon.mmap_mailbox.compression_threshold_bytes
            ),
            max_concurrent_requests=(
                settings.inference_daemon.mmap_mailbox.max_concurrent_requests
            ),
            poll_interval_seconds=(
                settings.inference_daemon.mmap_mailbox.poll_interval_seconds
            ),
        )
        if settings.inference_daemon.mmap_mailbox.enabled
        else None
    )
    return InferenceDaemonRuntime(
        settings=settings,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        async_local_buffer_broker_supervisor=async_local_buffer_broker_supervisor,
        task_runtimes=tuple(task_runtimes),
        deployment_runtime_reconciler=deployment_runtime_reconciler,
        control_dispatcher=control_dispatcher,
        local_mmap_server=local_mmap_server,
    )
