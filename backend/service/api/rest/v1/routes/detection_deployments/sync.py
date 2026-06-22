"""detection sync deployment 运行控制路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.detection_deployment_process_supervisor import (
    get_detection_sync_deployment_process_supervisor,
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
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_deployment_sync_router = APIRouter()


@detection_deployment_sync_router.post(
    "/detection/deployment-instances/{deployment_instance_id}/sync/start",
    response_model=DetectionDeploymentProcessStatusResponse,
)
def start_detection_sync_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_sync_deployment_process_supervisor)],
) -> DetectionDeploymentProcessStatusResponse:
    """启动一个 detection sync deployment 进程。"""

    return run_detection_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="sync",
        action="start",
    )


@detection_deployment_sync_router.post(
    "/detection/deployment-instances/{deployment_instance_id}/sync/stop",
    response_model=DetectionDeploymentProcessStatusResponse,
)
def stop_detection_sync_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_sync_deployment_process_supervisor)],
) -> DetectionDeploymentProcessStatusResponse:
    """停止一个 detection sync deployment 进程。"""

    return run_detection_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="sync",
        action="stop",
    )


@detection_deployment_sync_router.get(
    "/detection/deployment-instances/{deployment_instance_id}/sync/status",
    response_model=DetectionDeploymentProcessStatusResponse,
)
def get_detection_sync_deployment_status(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_sync_deployment_process_supervisor)],
) -> DetectionDeploymentProcessStatusResponse:
    """读取一个 detection sync deployment 监督状态。"""

    return run_detection_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="sync",
        action="status",
    )


@detection_deployment_sync_router.post(
    "/detection/deployment-instances/{deployment_instance_id}/sync/warmup",
    response_model=DetectionDeploymentRuntimeHealthResponse,
)
def warmup_detection_sync_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_sync_deployment_process_supervisor)],
) -> DetectionDeploymentRuntimeHealthResponse:
    """执行一个 detection sync deployment warmup。"""

    return run_detection_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="sync",
        action="warmup",
    )


@detection_deployment_sync_router.get(
    "/detection/deployment-instances/{deployment_instance_id}/sync/health",
    response_model=DetectionDeploymentRuntimeHealthResponse,
)
def get_detection_sync_deployment_health(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_sync_deployment_process_supervisor)],
) -> DetectionDeploymentRuntimeHealthResponse:
    """读取一个 detection sync deployment 健康状态。"""

    return run_detection_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="sync",
        action="health",
    )


@detection_deployment_sync_router.post(
    "/detection/deployment-instances/{deployment_instance_id}/sync/reset",
    response_model=DetectionDeploymentRuntimeHealthResponse,
)
def reset_detection_sync_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_sync_deployment_process_supervisor)],
) -> DetectionDeploymentRuntimeHealthResponse:
    """重置一个 detection sync deployment 推理实例池。"""

    return run_detection_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="sync",
        action="reset",
    )
