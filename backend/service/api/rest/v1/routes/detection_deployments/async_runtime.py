"""detection async deployment 运行控制路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.detection_deployment_process_supervisor import (
    get_detection_async_deployment_process_supervisor,
    get_detection_async_inference_gateway_dispatcher_registry,
)
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.detection_deployments.responses import (
    DetectionDeploymentProcessStatusResponse,
    DetectionDeploymentRuntimeHealthResponse,
)
from backend.service.api.rest.v1.routes.detection_deployments.runtime_actions import (
    run_detection_process_health_action,
    run_detection_process_status_action,
)
from backend.service.application.models.inference.detection_async_inference_gateway import (
    DetectionAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_deployment_async_router = APIRouter()


@detection_deployment_async_router.post(
    "/detection/deployment-instances/{deployment_instance_id}/async/start",
    response_model=DetectionDeploymentProcessStatusResponse,
)
def start_detection_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[
        DetectionAsyncInferenceGatewayDispatcherRegistry,
        Depends(get_detection_async_inference_gateway_dispatcher_registry),
    ],
) -> DetectionDeploymentProcessStatusResponse:
    """启动一个 detection async deployment 进程。"""

    return run_detection_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="start",
    )


@detection_deployment_async_router.post(
    "/detection/deployment-instances/{deployment_instance_id}/async/stop",
    response_model=DetectionDeploymentProcessStatusResponse,
)
def stop_detection_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[
        DetectionAsyncInferenceGatewayDispatcherRegistry,
        Depends(get_detection_async_inference_gateway_dispatcher_registry),
    ],
) -> DetectionDeploymentProcessStatusResponse:
    """停止一个 detection async deployment 进程。"""

    return run_detection_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="stop",
    )


@detection_deployment_async_router.get(
    "/detection/deployment-instances/{deployment_instance_id}/async/status",
    response_model=DetectionDeploymentProcessStatusResponse,
)
def get_detection_async_deployment_status(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[
        DetectionAsyncInferenceGatewayDispatcherRegistry,
        Depends(get_detection_async_inference_gateway_dispatcher_registry),
    ],
) -> DetectionDeploymentProcessStatusResponse:
    """读取一个 detection async deployment 监督状态。"""

    return run_detection_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="status",
    )


@detection_deployment_async_router.post(
    "/detection/deployment-instances/{deployment_instance_id}/async/warmup",
    response_model=DetectionDeploymentRuntimeHealthResponse,
)
def warmup_detection_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[
        DetectionAsyncInferenceGatewayDispatcherRegistry,
        Depends(get_detection_async_inference_gateway_dispatcher_registry),
    ],
) -> DetectionDeploymentRuntimeHealthResponse:
    """执行一个 detection async deployment warmup。"""

    return run_detection_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="warmup",
    )


@detection_deployment_async_router.get(
    "/detection/deployment-instances/{deployment_instance_id}/async/health",
    response_model=DetectionDeploymentRuntimeHealthResponse,
)
def get_detection_async_deployment_health(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[
        DetectionAsyncInferenceGatewayDispatcherRegistry,
        Depends(get_detection_async_inference_gateway_dispatcher_registry),
    ],
) -> DetectionDeploymentRuntimeHealthResponse:
    """读取一个 detection async deployment 健康状态。"""

    return run_detection_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="health",
    )


@detection_deployment_async_router.post(
    "/detection/deployment-instances/{deployment_instance_id}/async/reset",
    response_model=DetectionDeploymentRuntimeHealthResponse,
)
def reset_detection_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_async_deployment_process_supervisor)],
) -> DetectionDeploymentRuntimeHealthResponse:
    """重置一个 detection async deployment 推理实例池。"""

    return run_detection_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="async",
        action="reset",
    )
