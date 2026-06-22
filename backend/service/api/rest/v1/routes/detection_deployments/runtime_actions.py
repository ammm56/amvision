"""detection deployment 运行控制 helper。"""

from __future__ import annotations

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.api.rest.v1.routes.detection_deployments.responses import (
    DetectionDeploymentProcessStatusResponse,
    DetectionDeploymentRuntimeHealthResponse,
    build_detection_process_status_response,
    build_detection_runtime_health_response,
)
from backend.service.api.rest.v1.routes.detection_deployments.services import (
    build_detection_deployment_service,
    ensure_detection_deployment_visible,
)
from backend.service.application.models.inference.detection_async_inference_gateway import (
    DetectionAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def run_detection_process_status_action(
    *,
    deployment_instance_id: str,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    supervisor: DeploymentProcessSupervisor,
    gateway_dispatcher_registry: DetectionAsyncInferenceGatewayDispatcherRegistry | None = None,
    runtime_mode: str,
    action: str,
) -> DetectionDeploymentProcessStatusResponse:
    """执行指定通道的 detection deployment 进程状态动作。"""

    service = build_detection_deployment_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    view = service.get_deployment_instance(deployment_instance_id)
    ensure_detection_deployment_visible(principal=principal, view=view)
    process_config = service.resolve_process_config(deployment_instance_id)
    if action == "start":
        process_status = supervisor.start_deployment(process_config)
        if runtime_mode == "async" and gateway_dispatcher_registry is not None:
            gateway_dispatcher_registry.ensure_dispatcher_for_deployment(deployment_instance_id)
    elif action == "stop":
        process_status = supervisor.stop_deployment(process_config)
        if runtime_mode == "async" and gateway_dispatcher_registry is not None:
            gateway_dispatcher_registry.stop_dispatcher_for_deployment(deployment_instance_id)
    else:
        process_status = supervisor.get_status(process_config)
    return build_detection_process_status_response(view, process_status, runtime_mode)


def run_detection_process_health_action(
    *,
    deployment_instance_id: str,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    supervisor: DeploymentProcessSupervisor,
    gateway_dispatcher_registry: DetectionAsyncInferenceGatewayDispatcherRegistry | None = None,
    runtime_mode: str,
    action: str,
) -> DetectionDeploymentRuntimeHealthResponse:
    """执行指定通道的 detection deployment 进程健康动作。"""

    service = build_detection_deployment_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    view = service.get_deployment_instance(deployment_instance_id)
    ensure_detection_deployment_visible(principal=principal, view=view)
    process_config = service.resolve_process_config(deployment_instance_id)
    if action == "warmup":
        process_health = supervisor.warmup_deployment(process_config)
        if runtime_mode == "async" and gateway_dispatcher_registry is not None:
            gateway_dispatcher_registry.ensure_dispatcher_for_deployment(deployment_instance_id)
    elif action == "reset":
        process_health = supervisor.reset_deployment(process_config)
    else:
        process_health = supervisor.get_health(process_config)
    return build_detection_runtime_health_response(view, process_health, runtime_mode)
