"""Deployment supervisor 与 async gateway 的共享运行时工厂。"""

from __future__ import annotations

from backend.service.application.events import InMemoryServiceEventBus
from backend.service.application.local_buffers import LocalBufferBrokerProcessSupervisor
from backend.service.application.models.inference.classification_async_inference_gateway import (
    ClassificationAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.models.inference.detection_async_inference_gateway import (
    DetectionAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.models.inference.inference_gateway import (
    build_async_inference_preview_object_key,
    serialize_async_inference_execution_result,
)
from backend.service.application.models.inference.obb_async_inference_gateway import (
    ObbAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.models.inference.pose_async_inference_gateway import (
    PoseAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.models.inference.segmentation_async_inference_gateway import (
    SegmentationAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessConfig,
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.infrastructure.queue.local_file import LocalFileQueueBackend
from backend.service.settings import BackendServiceSettings

_GATEWAY_REGISTRY_CLASSES: dict[str, type] = {
    "detection": DetectionAsyncInferenceGatewayDispatcherRegistry,
    "classification": ClassificationAsyncInferenceGatewayDispatcherRegistry,
    "segmentation": SegmentationAsyncInferenceGatewayDispatcherRegistry,
    "pose": PoseAsyncInferenceGatewayDispatcherRegistry,
    "obb": ObbAsyncInferenceGatewayDispatcherRegistry,
}


def build_task_type_deployment_runtimes(
    *,
    task_type: str,
    dataset_storage: LocalDatasetStorage,
    service_event_bus: InMemoryServiceEventBus,
    session_factory: SessionFactory,
    local_buffer_broker_supervisor: LocalBufferBrokerProcessSupervisor,
    queue_backend: LocalFileQueueBackend,
    async_inference_service_id: str,
    settings: BackendServiceSettings,
    enable_direct_mmap_reader: bool = False,
) -> tuple[DeploymentProcessSupervisor, DeploymentProcessSupervisor, object]:
    """为一个 task type 构建 sync/async supervisor 和 async gateway。"""

    registry_class = _GATEWAY_REGISTRY_CLASSES.get(task_type)
    if registry_class is None:
        raise ValueError(f"不支持的 deployment task type: {task_type}")
    sync_supervisor = _build_deployment_supervisor(
        runtime_mode="sync",
        dataset_storage=dataset_storage,
        service_event_bus=service_event_bus,
        session_factory=session_factory,
        local_buffer_broker_supervisor=local_buffer_broker_supervisor,
        settings=settings,
        enable_direct_mmap_reader=enable_direct_mmap_reader,
    )
    async_supervisor = _build_deployment_supervisor(
        runtime_mode="async",
        dataset_storage=dataset_storage,
        service_event_bus=service_event_bus,
        session_factory=session_factory,
        local_buffer_broker_supervisor=local_buffer_broker_supervisor,
        settings=settings,
        enable_direct_mmap_reader=enable_direct_mmap_reader,
    )
    registry = registry_class(
        queue_backend=queue_backend,
        execution_handler=_build_async_inference_gateway_execution_handler(
            deployment_process_supervisor=async_supervisor,
            dataset_storage=dataset_storage,
            async_inference_service_id=async_inference_service_id,
        ),
        service_id=async_inference_service_id,
        dataset_storage=dataset_storage,
        request_queue_lease_timeout_seconds=max(
            1.0,
            settings.deployment_process_supervisor.request_timeout_seconds * 2,
        ),
        response_queue_retention_seconds=(
            settings.queue.response_queue_retention_seconds
        ),
    )
    return sync_supervisor, async_supervisor, registry


def _build_deployment_supervisor(
    *,
    runtime_mode: str,
    dataset_storage: LocalDatasetStorage,
    service_event_bus: InMemoryServiceEventBus,
    session_factory: SessionFactory,
    local_buffer_broker_supervisor: LocalBufferBrokerProcessSupervisor,
    settings: BackendServiceSettings,
    enable_direct_mmap_reader: bool,
) -> DeploymentProcessSupervisor:
    """构建一个进程监督器。"""

    return DeploymentProcessSupervisor(
        dataset_storage_root_dir=str(dataset_storage.root_dir),
        runtime_mode=runtime_mode,
        settings=settings.deployment_process_supervisor,
        service_event_bus=service_event_bus,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        local_buffer_broker_event_channel_provider=(
            local_buffer_broker_supervisor.get_event_channel
        ),
        local_buffer_direct_reader_settings=(
            settings.local_buffer_broker.model_dump(mode="python")
            if enable_direct_mmap_reader
            else None
        ),
        local_buffer_io=local_buffer_broker_supervisor,
    )


def _build_async_inference_gateway_execution_handler(
    *,
    deployment_process_supervisor: DeploymentProcessSupervisor,
    dataset_storage: LocalDatasetStorage,
    async_inference_service_id: str,
):
    """构造 async gateway 的 deployment 执行处理器。"""

    def execute(
        *,
        request_id: str,
        process_config: DeploymentProcessConfig,
        request: object,
    ) -> dict[str, object]:
        """通过指定 async supervisor 执行一次推理。"""

        execution_result = deployment_process_supervisor.run_inference(
            config=process_config,
            request=request,
        )
        preview_image_object_key: str | None = None
        preview_image_bytes = execution_result.execution_result.preview_image_bytes
        if preview_image_bytes is not None:
            preview_image_object_key = build_async_inference_preview_object_key(
                owner_id=async_inference_service_id,
                deployment_instance_id=process_config.deployment_instance_id,
                request_id=request_id,
            )
            dataset_storage.write_bytes(
                preview_image_object_key,
                preview_image_bytes,
            )
        return serialize_async_inference_execution_result(
            task_type=process_config.runtime_target.task_type,
            result=execution_result,
            preview_image_object_key=preview_image_object_key,
        )

    return execute
