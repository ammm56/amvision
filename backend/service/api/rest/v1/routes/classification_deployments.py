"""classification deployment 与运行控制 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.classification_deployment_process_supervisor import (
    get_classification_async_deployment_process_supervisor,
    get_classification_async_inference_gateway_dispatcher_registry,
    get_classification_sync_deployment_process_supervisor,
)
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.classification_deployment_helpers import (
    build_classification_deployment_instance_response,
)
from backend.service.api.rest.v1.routes.deployment_runtime_helpers import (
    DeploymentProcessStatusResponse,
    DeploymentRuntimeHealthResponse,
    run_deployment_process_health_action,
    run_deployment_process_status_action,
)
from backend.service.application.deployments.classification_deployment_service import (
    ClassificationDeploymentInstanceCreateRequest,
    SqlAlchemyClassificationDeploymentService,
)
from backend.service.application.errors import PermissionDeniedError
from backend.service.application.models.classification_async_inference_gateway import (
    ClassificationAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
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
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": body.project_id},
        )
    service = _build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage)
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
    service = _build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage)
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
    service = _build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage)
    view = service.get_deployment_instance(deployment_instance_id)
    _check_project_visible(principal, view.project_id)
    return build_classification_deployment_instance_response(view)


@classification_deployments_router.post(
    "/classification/deployment-instances/{deployment_instance_id}/sync/start",
    response_model=DeploymentProcessStatusResponse,
)
def start_classification_sync_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_sync_deployment_process_supervisor)],
) -> DeploymentProcessStatusResponse:
    return run_deployment_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="sync",
        action="start",
    )


@classification_deployments_router.post(
    "/classification/deployment-instances/{deployment_instance_id}/sync/stop",
    response_model=DeploymentProcessStatusResponse,
)
def stop_classification_sync_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_sync_deployment_process_supervisor)],
) -> DeploymentProcessStatusResponse:
    return run_deployment_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="sync",
        action="stop",
    )


@classification_deployments_router.get(
    "/classification/deployment-instances/{deployment_instance_id}/sync/status",
    response_model=DeploymentProcessStatusResponse,
)
def get_classification_sync_deployment_status(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_sync_deployment_process_supervisor)],
) -> DeploymentProcessStatusResponse:
    return run_deployment_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="sync",
        action="status",
    )


@classification_deployments_router.post(
    "/classification/deployment-instances/{deployment_instance_id}/sync/warmup",
    response_model=DeploymentRuntimeHealthResponse,
)
def warmup_classification_sync_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_sync_deployment_process_supervisor)],
) -> DeploymentRuntimeHealthResponse:
    return run_deployment_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="sync",
        action="warmup",
    )


@classification_deployments_router.get(
    "/classification/deployment-instances/{deployment_instance_id}/sync/health",
    response_model=DeploymentRuntimeHealthResponse,
)
def get_classification_sync_deployment_health(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_sync_deployment_process_supervisor)],
) -> DeploymentRuntimeHealthResponse:
    return run_deployment_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="sync",
        action="health",
    )


@classification_deployments_router.post(
    "/classification/deployment-instances/{deployment_instance_id}/sync/reset",
    response_model=DeploymentRuntimeHealthResponse,
)
def reset_classification_sync_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_sync_deployment_process_supervisor)],
) -> DeploymentRuntimeHealthResponse:
    return run_deployment_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="sync",
        action="reset",
    )


@classification_deployments_router.post(
    "/classification/deployment-instances/{deployment_instance_id}/async/start",
    response_model=DeploymentProcessStatusResponse,
)
def start_classification_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[ClassificationAsyncInferenceGatewayDispatcherRegistry, Depends(get_classification_async_inference_gateway_dispatcher_registry)],
) -> DeploymentProcessStatusResponse:
    return run_deployment_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="start",
    )


@classification_deployments_router.post(
    "/classification/deployment-instances/{deployment_instance_id}/async/stop",
    response_model=DeploymentProcessStatusResponse,
)
def stop_classification_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[ClassificationAsyncInferenceGatewayDispatcherRegistry, Depends(get_classification_async_inference_gateway_dispatcher_registry)],
) -> DeploymentProcessStatusResponse:
    return run_deployment_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="stop",
    )


@classification_deployments_router.get(
    "/classification/deployment-instances/{deployment_instance_id}/async/status",
    response_model=DeploymentProcessStatusResponse,
)
def get_classification_async_deployment_status(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[ClassificationAsyncInferenceGatewayDispatcherRegistry, Depends(get_classification_async_inference_gateway_dispatcher_registry)],
) -> DeploymentProcessStatusResponse:
    return run_deployment_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="status",
    )


@classification_deployments_router.post(
    "/classification/deployment-instances/{deployment_instance_id}/async/warmup",
    response_model=DeploymentRuntimeHealthResponse,
)
def warmup_classification_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[ClassificationAsyncInferenceGatewayDispatcherRegistry, Depends(get_classification_async_inference_gateway_dispatcher_registry)],
) -> DeploymentRuntimeHealthResponse:
    return run_deployment_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="warmup",
    )


@classification_deployments_router.get(
    "/classification/deployment-instances/{deployment_instance_id}/async/health",
    response_model=DeploymentRuntimeHealthResponse,
)
def get_classification_async_deployment_health(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[ClassificationAsyncInferenceGatewayDispatcherRegistry, Depends(get_classification_async_inference_gateway_dispatcher_registry)],
) -> DeploymentRuntimeHealthResponse:
    return run_deployment_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="health",
    )


@classification_deployments_router.post(
    "/classification/deployment-instances/{deployment_instance_id}/async/reset",
    response_model=DeploymentRuntimeHealthResponse,
)
def reset_classification_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_async_deployment_process_supervisor)],
) -> DeploymentRuntimeHealthResponse:
    return run_deployment_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=_build_classification_deployment_service(session_factory=session_factory, dataset_storage=dataset_storage),
        supervisor=supervisor,
        runtime_mode="async",
        action="reset",
    )


def _build_classification_deployment_service(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> SqlAlchemyClassificationDeploymentService:
    """构建 classification deployment 公共服务。"""

    return SqlAlchemyClassificationDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


def _check_project_visible(principal: AuthenticatedPrincipal, project_id: str) -> None:
    """校验当前主体是否可以访问指定 Project。"""

    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError("当前主体无权访问该 Project", details={"project_id": project_id})
