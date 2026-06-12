"""obb deployment REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.obb_deployment_process_supervisor import (
    get_obb_async_deployment_process_supervisor,
    get_obb_async_inference_gateway_dispatcher_registry,
    get_obb_sync_deployment_process_supervisor,
)
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.deployment_runtime_helpers import (
    DeploymentProcessStatusResponse,
    DeploymentRuntimeHealthResponse,
    run_deployment_process_health_action,
    run_deployment_process_status_action,
)
from backend.service.api.rest.v1.routes.obb_deployment_helpers import (
    build_obb_deployment_instance_response,
)
from backend.service.application.deployments.obb_deployment_service import (
    ObbDeploymentInstanceCreateRequest,
    SqlAlchemyObbDeploymentService,
)
from backend.service.application.errors import PermissionDeniedError
from backend.service.application.models.obb_async_inference_gateway import (
    ObbAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


obb_deployments_router = APIRouter(prefix="/models", tags=["models"])


class ObbDeploymentInstanceCreateRequestBody(BaseModel):
    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description="模型分类；支持 yolov8、yolo11、yolo26")
    model_version_id: str | None = Field(default=None)
    model_build_id: str | None = Field(default=None)
    runtime_profile_id: str | None = Field(default=None)
    runtime_backend: str | None = Field(default=None)
    runtime_precision: str | None = Field(default=None)
    device_name: str | None = Field(default=None)
    instance_count: int = Field(default=1, ge=1)
    display_name: str = Field(default="")
    metadata: dict[str, object] = Field(default_factory=dict)


class ObbDeploymentInstanceResponse(BaseModel):
    deployment_instance_id: str
    project_id: str
    model_id: str
    model_version_id: str | None = None
    model_build_id: str | None = None
    display_name: str
    status: str
    runtime_profile_id: str | None = None
    runtime_backend: str
    device_name: str
    instance_count: int
    process_status: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    created_by: str | None = None


@obb_deployments_router.post(
    "/obb/deployment-instances",
    response_model=ObbDeploymentInstanceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_obb_deployment_instance(
    body: ObbDeploymentInstanceCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ObbDeploymentInstanceResponse:
    _check_project(principal, body.project_id)
    service = _build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage)
    view = service.create_deployment_instance(
        ObbDeploymentInstanceCreateRequest(
            project_id=body.project_id,
            model_type=body.model_type,
            model_version_id=body.model_version_id,
            model_build_id=body.model_build_id,
            runtime_profile_id=body.runtime_profile_id,
            runtime_backend=body.runtime_backend,
            runtime_precision=body.runtime_precision,
            device_name=body.device_name,
            instance_count=body.instance_count,
            display_name=body.display_name,
            metadata=dict(body.metadata),
        ),
        created_by=principal.principal_id,
    )
    return build_obb_deployment_instance_response(view)


@obb_deployments_router.get(
    "/obb/deployment-instances",
    response_model=list[ObbDeploymentInstanceResponse],
)
def list_obb_deployment_instances(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    project_id: Annotated[str | None, Query()] = None,
    model_type: Annotated[str | None, Query()] = None,
    model_version_id: Annotated[str | None, Query()] = None,
    model_build_id: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[ObbDeploymentInstanceResponse]:
    if principal.project_ids and project_id is not None and project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project", details={"project_id": project_id})
    service = _build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage)
    views = service.list_deployment_instances(
        project_id=project_id or "",
        model_type=model_type,
        model_version_id=model_version_id,
        model_build_id=model_build_id,
        status=status_filter,
        limit=limit,
    )
    return [build_obb_deployment_instance_response(v) for v in views]


@obb_deployments_router.get(
    "/obb/deployment-instances/{deployment_instance_id}",
    response_model=ObbDeploymentInstanceResponse,
)
def get_obb_deployment_instance(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ObbDeploymentInstanceResponse:
    service = _build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage)
    view = service.get_deployment_instance(deployment_instance_id)
    _check_project(principal, view.project_id)
    return build_obb_deployment_instance_response(view)


@obb_deployments_router.post(
    "/obb/deployment-instances/{deployment_instance_id}/sync/start",
    response_model=DeploymentProcessStatusResponse,
)
def start_obb_sync_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_obb_sync_deployment_process_supervisor)],
) -> DeploymentProcessStatusResponse:
    return run_deployment_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="sync",
        action="start",
    )


@obb_deployments_router.post(
    "/obb/deployment-instances/{deployment_instance_id}/sync/stop",
    response_model=DeploymentProcessStatusResponse,
)
def stop_obb_sync_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_obb_sync_deployment_process_supervisor)],
) -> DeploymentProcessStatusResponse:
    return run_deployment_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="sync",
        action="stop",
    )


@obb_deployments_router.get(
    "/obb/deployment-instances/{deployment_instance_id}/sync/status",
    response_model=DeploymentProcessStatusResponse,
)
def get_obb_sync_deployment_status(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_obb_sync_deployment_process_supervisor)],
) -> DeploymentProcessStatusResponse:
    return run_deployment_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="sync",
        action="status",
    )


@obb_deployments_router.post(
    "/obb/deployment-instances/{deployment_instance_id}/sync/warmup",
    response_model=DeploymentRuntimeHealthResponse,
)
def warmup_obb_sync_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_obb_sync_deployment_process_supervisor)],
) -> DeploymentRuntimeHealthResponse:
    return run_deployment_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="sync",
        action="warmup",
    )


@obb_deployments_router.get(
    "/obb/deployment-instances/{deployment_instance_id}/sync/health",
    response_model=DeploymentRuntimeHealthResponse,
)
def get_obb_sync_deployment_health(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_obb_sync_deployment_process_supervisor)],
) -> DeploymentRuntimeHealthResponse:
    return run_deployment_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="sync",
        action="health",
    )


@obb_deployments_router.post(
    "/obb/deployment-instances/{deployment_instance_id}/sync/reset",
    response_model=DeploymentRuntimeHealthResponse,
)
def reset_obb_sync_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_obb_sync_deployment_process_supervisor)],
) -> DeploymentRuntimeHealthResponse:
    return run_deployment_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="sync",
        action="reset",
    )


@obb_deployments_router.post(
    "/obb/deployment-instances/{deployment_instance_id}/async/start",
    response_model=DeploymentProcessStatusResponse,
)
def start_obb_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_obb_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[ObbAsyncInferenceGatewayDispatcherRegistry, Depends(get_obb_async_inference_gateway_dispatcher_registry)],
) -> DeploymentProcessStatusResponse:
    return run_deployment_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="start",
    )


@obb_deployments_router.post(
    "/obb/deployment-instances/{deployment_instance_id}/async/stop",
    response_model=DeploymentProcessStatusResponse,
)
def stop_obb_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_obb_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[ObbAsyncInferenceGatewayDispatcherRegistry, Depends(get_obb_async_inference_gateway_dispatcher_registry)],
) -> DeploymentProcessStatusResponse:
    return run_deployment_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="stop",
    )


@obb_deployments_router.get(
    "/obb/deployment-instances/{deployment_instance_id}/async/status",
    response_model=DeploymentProcessStatusResponse,
)
def get_obb_async_deployment_status(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_obb_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[ObbAsyncInferenceGatewayDispatcherRegistry, Depends(get_obb_async_inference_gateway_dispatcher_registry)],
) -> DeploymentProcessStatusResponse:
    return run_deployment_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="status",
    )


@obb_deployments_router.post(
    "/obb/deployment-instances/{deployment_instance_id}/async/warmup",
    response_model=DeploymentRuntimeHealthResponse,
)
def warmup_obb_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_obb_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[ObbAsyncInferenceGatewayDispatcherRegistry, Depends(get_obb_async_inference_gateway_dispatcher_registry)],
) -> DeploymentRuntimeHealthResponse:
    return run_deployment_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="warmup",
    )


@obb_deployments_router.get(
    "/obb/deployment-instances/{deployment_instance_id}/async/health",
    response_model=DeploymentRuntimeHealthResponse,
)
def get_obb_async_deployment_health(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_obb_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[ObbAsyncInferenceGatewayDispatcherRegistry, Depends(get_obb_async_inference_gateway_dispatcher_registry)],
) -> DeploymentRuntimeHealthResponse:
    return run_deployment_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="health",
    )


@obb_deployments_router.post(
    "/obb/deployment-instances/{deployment_instance_id}/async/reset",
    response_model=DeploymentRuntimeHealthResponse,
)
def reset_obb_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_obb_async_deployment_process_supervisor)],
) -> DeploymentRuntimeHealthResponse:
    return run_deployment_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_obb_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="async",
        action="reset",
    )


def _build_obb_deployment_service(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> SqlAlchemyObbDeploymentService:
    """构建 obb deployment 公共服务。"""

    return SqlAlchemyObbDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


def _check_project(principal: AuthenticatedPrincipal, project_id: str) -> None:
    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project", details={"project_id": project_id})
