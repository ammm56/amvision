"""classification deployment 与运行控制 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.classification_deployment_process_supervisor import (
    get_classification_async_deployment_process_supervisor,
    get_classification_sync_deployment_process_supervisor,
)
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.classification_deployment_helpers import (
    build_classification_deployment_instance_response,
)
from backend.service.application.deployments.classification_deployment_service import (
    ClassificationDeploymentInstanceCreateRequest,
    SqlAlchemyClassificationDeploymentService,
)
from backend.service.application.errors import PermissionDeniedError, ResourceNotFoundError, ServiceConfigurationError
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


classification_deployments_router = APIRouter(prefix="/models", tags=["models"])


class ClassificationDeploymentInstanceCreateRequestBody(BaseModel):
    """描述 classification DeploymentInstance 创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description="模型分类；当前支持 yolov8、yolo11、yolo26")
    model_version_id: str | None = Field(default=None, description="直接绑定的 ModelVersion id")
    model_build_id: str | None = Field(default=None, description="直接绑定的 ModelBuild id")
    runtime_profile_id: str | None = Field(default=None, description="可选 RuntimeProfile id")
    runtime_backend: str | None = Field(default=None, description="运行时 backend")
    runtime_precision: str | None = Field(default=None, description="运行时 precision")
    device_name: str | None = Field(default=None, description="默认 device 名称")
    instance_count: int = Field(default=1, ge=1, description="实例化数量")
    display_name: str = Field(default="", description="展示名称")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class ClassificationDeploymentInstanceResponse(BaseModel):
    deployment_instance_id: str = Field(description="DeploymentInstance id")
    project_id: str = Field(description="所属 Project id")
    model_id: str = Field(description="关联 Model id")
    model_version_id: str | None = Field(default=None, description="绑定的 ModelVersion id")
    model_build_id: str | None = Field(default=None, description="绑定的 ModelBuild id")
    display_name: str = Field(description="展示名称")
    status: str = Field(description="实例状态")
    runtime_profile_id: str | None = Field(default=None, description="RuntimeProfile id")
    runtime_backend: str = Field(description="运行时 backend")
    device_name: str = Field(description="默认 device 名称")
    instance_count: int = Field(description="期望实例数")
    process_status: str | None = Field(default=None, description="进程运行状态")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="最近更新时间")
    created_by: str | None = Field(default=None, description="创建主体 id")


@classification_deployments_router.post(
    "/classification/deployment-instances",
    response_model=ClassificationDeploymentInstanceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_classification_deployment_instance(
    body: ClassificationDeploymentInstanceCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ClassificationDeploymentInstanceResponse:
    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError("当前主体无权访问该 Project", details={"project_id": body.project_id})
    service = SqlAlchemyClassificationDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    view = service.create_deployment_instance(
        ClassificationDeploymentInstanceCreateRequest(
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
    return build_classification_deployment_instance_response(view)


@classification_deployments_router.get(
    "/classification/deployment-instances",
    response_model=list[ClassificationDeploymentInstanceResponse],
)
def list_classification_deployment_instances(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    model_type: Annotated[str | None, Query(description="模型分类")] = None,
    model_version_id: Annotated[str | None, Query(description="绑定的 ModelVersion id")] = None,
    model_build_id: Annotated[str | None, Query(description="绑定的 ModelBuild id")] = None,
    status_filter: Annotated[str | None, Query(alias="status", description="实例状态")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="最大返回数量")] = 100,
) -> list[ClassificationDeploymentInstanceResponse]:
    if principal.project_ids and project_id is not None and project_id not in principal.project_ids:
        raise PermissionDeniedError("当前主体无权访问该 Project", details={"project_id": project_id})
    service = SqlAlchemyClassificationDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    views = service.list_deployment_instances(
        project_id=project_id or "",
        model_type=model_type,
        model_version_id=model_version_id,
        model_build_id=model_build_id,
        status=status_filter,
        limit=limit,
    )
    return [build_classification_deployment_instance_response(v) for v in views]


@classification_deployments_router.get(
    "/classification/deployment-instances/{deployment_instance_id}",
    response_model=ClassificationDeploymentInstanceResponse,
)
def get_classification_deployment_instance(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ClassificationDeploymentInstanceResponse:
    service = SqlAlchemyClassificationDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    try:
        view = service.get_deployment_instance(deployment_instance_id)
    except ResourceNotFoundError:
        raise
    if principal.project_ids and view.project_id not in principal.project_ids:
        raise PermissionDeniedError("当前主体无权访问该 Project", details={"project_id": view.project_id})
    return build_classification_deployment_instance_response(view)


@classification_deployments_router.post(
    "/classification/deployment-instances/{deployment_instance_id}/sync/start",
    status_code=status.HTTP_200_OK,
)
def sync_start_classification_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_classification_sync_deployment_process_supervisor)],
) -> dict[str, str]:
    _require_supervisor(supervisor)
    service = SqlAlchemyClassificationDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    _check_project_visible(principal, service.get_deployment_instance(deployment_instance_id))
    supervisor.sync_start(deployment_instance_id)
    return {"status": "started", "deployment_instance_id": deployment_instance_id}


@classification_deployments_router.post(
    "/classification/deployment-instances/{deployment_instance_id}/sync/stop",
    status_code=status.HTTP_200_OK,
)
def sync_stop_classification_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_classification_sync_deployment_process_supervisor)],
) -> dict[str, str]:
    _require_supervisor(supervisor)
    service = SqlAlchemyClassificationDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    _check_project_visible(principal, service.get_deployment_instance(deployment_instance_id))
    supervisor.sync_stop(deployment_instance_id)
    return {"status": "stopped", "deployment_instance_id": deployment_instance_id}


@classification_deployments_router.post(
    "/classification/deployment-instances/{deployment_instance_id}/sync/health",
    status_code=status.HTTP_200_OK,
)
def sync_health_classification_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_classification_sync_deployment_process_supervisor)],
) -> dict[str, object]:
    _require_supervisor(supervisor)
    service = SqlAlchemyClassificationDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    _check_project_visible(principal, service.get_deployment_instance(deployment_instance_id))
    report = supervisor.check_health(deployment_instance_id)
    return {"deployment_instance_id": deployment_instance_id, "healthy": report.healthy, "details": report.details}


def _check_project_visible(
    principal: AuthenticatedPrincipal,
    view: object,
) -> None:
    if principal.project_ids and getattr(view, "project_id", None) not in principal.project_ids:
        raise PermissionDeniedError("当前主体无权访问该 Project", details={"project_id": getattr(view, "project_id", "")})


def _require_supervisor(supervisor: YoloXDeploymentProcessSupervisor | None) -> YoloXDeploymentProcessSupervisor:
    if supervisor is None:
        raise ServiceConfigurationError("classification deployment process supervisor 未启动", details={"cause": "no-supervisor"})
    return supervisor
