"""detection deployment 与运行控制 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.detection_deployment_process_supervisor import (
    get_detection_async_deployment_process_supervisor,
    get_detection_async_inference_gateway_dispatcher_registry,
    get_detection_sync_deployment_process_supervisor,
)
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.detection_deployment_helpers import (
    DetectionDeploymentInstanceResponse,
    DetectionDeploymentProcessEventResponse,
    DetectionDeploymentProcessStatusResponse,
    DetectionDeploymentRuntimeHealthResponse,
    _build_detection_deployment_instance_response,
    _build_detection_deployment_process_event_response,
    _ensure_detection_deployment_visible,
    _run_detection_process_health_action,
    _run_detection_process_status_action,
)
from backend.service.application.deployments.detection_deployment_service import (
    DetectionDeploymentInstanceCreateRequest,
    SqlAlchemyDetectionDeploymentService,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError
from backend.service.application.models.detection_async_inference_gateway import (
    DetectionAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.application.runtime.deployment_event_source import DetectionDeploymentEventSource
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_deployments_router = APIRouter(prefix="/models", tags=["models"])


class DetectionDeploymentInstanceCreateRequestBody(BaseModel):
    """描述 detection DeploymentInstance 创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description="模型分类；当前支持 yolox、yolov8、yolo11、yolo26")
    model_version_id: str | None = Field(default=None, description="直接绑定的 ModelVersion id")
    model_build_id: str | None = Field(default=None, description="直接绑定的 ModelBuild id")
    runtime_profile_id: str | None = Field(default=None, description="可选 RuntimeProfile id")
    runtime_backend: str | None = Field(default=None, description="运行时 backend")
    runtime_precision: str | None = Field(default=None, description="运行时 precision")
    device_name: str | None = Field(default=None, description="默认 device 名称")
    instance_count: int = Field(default=1, ge=1, description="实例化数量")
    display_name: str = Field(default="", description="展示名称")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


@detection_deployments_router.post(
    "/detection/deployment-instances",
    response_model=DetectionDeploymentInstanceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_detection_deployment_instance(
    body: DetectionDeploymentInstanceCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionDeploymentInstanceResponse:
    """创建一个 detection DeploymentInstance。"""

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": body.project_id},
        )
    service = SqlAlchemyDetectionDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    view = service.create_deployment_instance(
        DetectionDeploymentInstanceCreateRequest(
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
    return _build_detection_deployment_instance_response(view)


@detection_deployments_router.get(
    "/detection/deployment-instances",
    response_model=list[DetectionDeploymentInstanceResponse],
)
def list_detection_deployment_instances(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    model_type: Annotated[str | None, Query(description="模型分类")] = None,
    model_version_id: Annotated[str | None, Query(description="绑定的 ModelVersion id")] = None,
    model_build_id: Annotated[str | None, Query(description="绑定的 ModelBuild id")] = None,
    status_filter: Annotated[str | None, Query(alias="status", description="实例状态")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="最大返回数量")] = 100,
) -> list[DetectionDeploymentInstanceResponse]:
    """列出当前主体可见的 detection DeploymentInstance。"""

    visible_project_ids = tuple(principal.project_ids or ())
    resolved_project_id = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
    if resolved_project_id is None:
        if not visible_project_ids:
            raise PermissionDeniedError("当前主体缺少可访问 Project 范围")
        resolved_project_id = visible_project_ids[0]
    elif visible_project_ids and resolved_project_id not in visible_project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": resolved_project_id},
        )
    service = SqlAlchemyDetectionDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    views = service.list_deployment_instances(
        project_id=resolved_project_id,
        model_type=model_type,
        model_version_id=model_version_id,
        model_build_id=model_build_id,
        status=status_filter,
        limit=limit,
    )
    return [_build_detection_deployment_instance_response(item) for item in views]


@detection_deployments_router.get(
    "/detection/deployment-instances/{deployment_instance_id}",
    response_model=DetectionDeploymentInstanceResponse,
)
def get_detection_deployment_instance(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionDeploymentInstanceResponse:
    """读取一个 detection DeploymentInstance。"""

    service = SqlAlchemyDetectionDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    view = service.get_deployment_instance(deployment_instance_id)
    _ensure_detection_deployment_visible(principal=principal, view=view)
    return _build_detection_deployment_instance_response(view)


@detection_deployments_router.get(
    "/detection/deployment-instances/{deployment_instance_id}/events",
    response_model=list[DetectionDeploymentProcessEventResponse],
)
def get_detection_deployment_events(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    after_sequence: Annotated[int | None, Query(description="只返回 sequence 大于该值的事件", ge=0)] = None,
    limit: Annotated[int | None, Query(description="最多返回多少条事件", ge=1, le=500)] = None,
    runtime_mode: Annotated[str | None, Query(description="按 sync 或 async 通道过滤事件")] = None,
) -> list[DetectionDeploymentProcessEventResponse]:
    """读取一条 detection DeploymentInstance 的事件列表。"""

    service = SqlAlchemyDetectionDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    view = service.get_deployment_instance(deployment_instance_id)
    _ensure_detection_deployment_visible(principal=principal, view=view)
    if runtime_mode is not None and runtime_mode not in {"sync", "async"}:
        raise InvalidRequestError(
            "runtime_mode 仅支持 sync 或 async",
            details={"runtime_mode": runtime_mode},
        )
    event_source = DetectionDeploymentEventSource(
        dataset_storage_root_dir=str(dataset_storage.root_dir),
    )
    events = event_source.list_events(
        deployment_instance_id,
        after_sequence=after_sequence,
        runtime_mode=runtime_mode,
        limit=limit,
    )
    return [_build_detection_deployment_process_event_response(item) for item in events]


@detection_deployments_router.delete(
    "/detection/deployment-instances/{deployment_instance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_detection_deployment_instance(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> None:
    """删除一个 detection DeploymentInstance。"""

    service = SqlAlchemyDetectionDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    view = service.get_deployment_instance(deployment_instance_id)
    _ensure_detection_deployment_visible(principal=principal, view=view)
    service.delete_deployment_instance(deployment_instance_id)


@detection_deployments_router.post(
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

    return _run_detection_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="sync",
        action="start",
    )


@detection_deployments_router.post(
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

    return _run_detection_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="sync",
        action="stop",
    )


@detection_deployments_router.get(
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

    return _run_detection_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="sync",
        action="status",
    )


@detection_deployments_router.post(
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

    return _run_detection_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="sync",
        action="warmup",
    )


@detection_deployments_router.get(
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

    return _run_detection_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="sync",
        action="health",
    )


@detection_deployments_router.post(
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

    return _run_detection_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="sync",
        action="reset",
    )


@detection_deployments_router.post(
    "/detection/deployment-instances/{deployment_instance_id}/async/start",
    response_model=DetectionDeploymentProcessStatusResponse,
)
def start_detection_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[DetectionAsyncInferenceGatewayDispatcherRegistry, Depends(get_detection_async_inference_gateway_dispatcher_registry)],
) -> DetectionDeploymentProcessStatusResponse:
    """启动一个 detection async deployment 进程。"""

    return _run_detection_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="start",
    )


@detection_deployments_router.post(
    "/detection/deployment-instances/{deployment_instance_id}/async/stop",
    response_model=DetectionDeploymentProcessStatusResponse,
)
def stop_detection_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[DetectionAsyncInferenceGatewayDispatcherRegistry, Depends(get_detection_async_inference_gateway_dispatcher_registry)],
) -> DetectionDeploymentProcessStatusResponse:
    """停止一个 detection async deployment 进程。"""

    return _run_detection_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="stop",
    )


@detection_deployments_router.get(
    "/detection/deployment-instances/{deployment_instance_id}/async/status",
    response_model=DetectionDeploymentProcessStatusResponse,
)
def get_detection_async_deployment_status(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[DetectionAsyncInferenceGatewayDispatcherRegistry, Depends(get_detection_async_inference_gateway_dispatcher_registry)],
) -> DetectionDeploymentProcessStatusResponse:
    """读取一个 detection async deployment 监督状态。"""

    return _run_detection_process_status_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="status",
    )


@detection_deployments_router.post(
    "/detection/deployment-instances/{deployment_instance_id}/async/warmup",
    response_model=DetectionDeploymentRuntimeHealthResponse,
)
def warmup_detection_async_deployment(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[DetectionAsyncInferenceGatewayDispatcherRegistry, Depends(get_detection_async_inference_gateway_dispatcher_registry)],
) -> DetectionDeploymentRuntimeHealthResponse:
    """执行一个 detection async deployment warmup。"""

    return _run_detection_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="warmup",
    )


@detection_deployments_router.get(
    "/detection/deployment-instances/{deployment_instance_id}/async/health",
    response_model=DetectionDeploymentRuntimeHealthResponse,
)
def get_detection_async_deployment_health(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[DetectionAsyncInferenceGatewayDispatcherRegistry, Depends(get_detection_async_inference_gateway_dispatcher_registry)],
) -> DetectionDeploymentRuntimeHealthResponse:
    """读取一个 detection async deployment 健康状态。"""

    return _run_detection_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
        runtime_mode="async",
        action="health",
    )


@detection_deployments_router.post(
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

    return _run_detection_process_health_action(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        supervisor=supervisor,
        runtime_mode="async",
        action="reset",
    )
