"""pose deployment REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.pose_deployment_process_supervisor import (
    get_pose_async_deployment_process_supervisor,
    get_pose_sync_deployment_process_supervisor,
)
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.pose_deployment_helpers import (
    build_pose_deployment_instance_response,
)
from backend.service.application.deployments.pose_deployment_service import (
    PoseDeploymentInstanceCreateRequest,
    SqlAlchemyPoseDeploymentService,
)
from backend.service.application.errors import PermissionDeniedError, ResourceNotFoundError, ServiceConfigurationError
from backend.service.application.runtime.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


pose_deployments_router = APIRouter(prefix="/models", tags=["models"])


class PoseDeploymentInstanceCreateRequestBody(BaseModel):
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


class PoseDeploymentInstanceResponse(BaseModel):
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


@pose_deployments_router.post(
    "/pose/deployment-instances",
    response_model=PoseDeploymentInstanceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_pose_deployment_instance(
    body: PoseDeploymentInstanceCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> PoseDeploymentInstanceResponse:
    _check_project(principal, body.project_id)
    service = SqlAlchemyPoseDeploymentService(session_factory=session_factory, dataset_storage=dataset_storage)
    view = service.create_deployment_instance(
        PoseDeploymentInstanceCreateRequest(
            project_id=body.project_id, model_type=body.model_type, model_version_id=body.model_version_id,
            model_build_id=body.model_build_id, runtime_profile_id=body.runtime_profile_id,
            runtime_backend=body.runtime_backend, runtime_precision=body.runtime_precision,
            device_name=body.device_name, instance_count=body.instance_count,
            display_name=body.display_name, metadata=dict(body.metadata),
        ),
        created_by=principal.principal_id,
    )
    return build_pose_deployment_instance_response(view)


@pose_deployments_router.get(
    "/pose/deployment-instances",
    response_model=list[PoseDeploymentInstanceResponse],
)
def list_pose_deployment_instances(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    project_id: Annotated[str | None, Query()] = None,
    model_type: Annotated[str | None, Query()] = None,
    model_version_id: Annotated[str | None, Query()] = None,
    model_build_id: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[PoseDeploymentInstanceResponse]:
    if principal.project_ids and project_id is not None and project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project", details={"project_id": project_id})
    service = SqlAlchemyPoseDeploymentService(session_factory=session_factory, dataset_storage=dataset_storage)
    views = service.list_deployment_instances(project_id=project_id or "", model_type=model_type, model_version_id=model_version_id, model_build_id=model_build_id, status=status_filter, limit=limit)
    return [build_pose_deployment_instance_response(v) for v in views]


@pose_deployments_router.get(
    "/pose/deployment-instances/{deployment_instance_id}",
    response_model=PoseDeploymentInstanceResponse,
)
def get_pose_deployment_instance(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> PoseDeploymentInstanceResponse:
    service = SqlAlchemyPoseDeploymentService(session_factory=session_factory, dataset_storage=dataset_storage)
    view = service.get_deployment_instance(deployment_instance_id)
    _check_project(principal, view.project_id)
    return build_pose_deployment_instance_response(view)


@pose_deployments_router.post("/pose/deployment-instances/{deployment_instance_id}/sync/start")
def sync_start_pose_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_pose_sync_deployment_process_supervisor)],
) -> dict[str, str]:
    _require_sup(supervisor)
    service = SqlAlchemyPoseDeploymentService(session_factory=session_factory, dataset_storage=dataset_storage)
    _check_project(principal, service.get_deployment_instance(deployment_instance_id).project_id)
    supervisor.sync_start(deployment_instance_id)
    return {"status": "started", "deployment_instance_id": deployment_instance_id}


@pose_deployments_router.post("/pose/deployment-instances/{deployment_instance_id}/sync/stop")
def sync_stop_pose_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_pose_sync_deployment_process_supervisor)],
) -> dict[str, str]:
    _require_sup(supervisor)
    service = SqlAlchemyPoseDeploymentService(session_factory=session_factory, dataset_storage=dataset_storage)
    _check_project(principal, service.get_deployment_instance(deployment_instance_id).project_id)
    supervisor.sync_stop(deployment_instance_id)
    return {"status": "stopped", "deployment_instance_id": deployment_instance_id}


@pose_deployments_router.post("/pose/deployment-instances/{deployment_instance_id}/sync/health")
def sync_health_pose_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_pose_sync_deployment_process_supervisor)],
) -> dict[str, object]:
    _require_sup(supervisor)
    service = SqlAlchemyPoseDeploymentService(session_factory=session_factory, dataset_storage=dataset_storage)
    _check_project(principal, service.get_deployment_instance(deployment_instance_id).project_id)
    report = supervisor.check_health(deployment_instance_id)
    return {"deployment_instance_id": deployment_instance_id, "healthy": report.healthy, "details": report.details}


def _check_project(principal: AuthenticatedPrincipal, project_id: str) -> None:
    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project", details={"project_id": project_id})


def _require_sup(s: DeploymentProcessSupervisor | None) -> DeploymentProcessSupervisor:
    if s is None:
        raise ServiceConfigurationError("pose deployment supervisor 未启动", details={"cause": "no-supervisor"})
    return s
