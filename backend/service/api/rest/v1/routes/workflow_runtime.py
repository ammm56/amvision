"""workflow runtime 控制面 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from backend.contracts.workflows import (
    FlowApplication,
    WorkflowAppRuntimeInstanceContract,
    WorkflowAppRuntimeContract,
    WorkflowGraphTemplate,
    WorkflowPreviewRunContract,
    WorkflowRunContract,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.application.errors import PermissionDeniedError, ServiceConfigurationError
from backend.service.application.workflows.runtime_service import (
    WorkflowAppRuntimeCreateRequest,
    WorkflowPreviewRunCreateRequest,
    WorkflowRuntimeInvokeRequest,
    WorkflowRuntimeService,
)
from backend.service.application.workflows.runtime_worker import WorkflowRuntimeWorkerManager
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowPreviewRun,
    WorkflowRun,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import BackendServiceSettings


workflow_runtime_router = APIRouter(prefix="/workflows", tags=["workflow-runtime"])


class WorkflowApplicationRefRequestBody(BaseModel):
    """描述 preview run 请求体里的 application 引用。"""

    application_id: str = Field(description="已保存 FlowApplication id")


class WorkflowPreviewRunCreateRequestBody(BaseModel):
    """描述 preview run 创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    application_ref: WorkflowApplicationRefRequestBody | None = Field(
        default=None,
        description="可选的已保存 application 引用",
    )
    application: FlowApplication | None = Field(default=None, description="可选 inline application snapshot")
    template: WorkflowGraphTemplate | None = Field(default=None, description="可选 inline template snapshot")
    input_bindings: dict[str, object] = Field(default_factory=dict, description="输入绑定 payload")
    execution_metadata: dict[str, object] = Field(default_factory=dict, description="执行元数据")
    timeout_seconds: int = Field(default=30, description="同步等待超时秒数")


class WorkflowAppRuntimeCreateRequestBody(BaseModel):
    """描述 app runtime 创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    application_id: str = Field(description="已保存 FlowApplication id")
    display_name: str = Field(default="", description="可选展示名称")
    request_timeout_seconds: int = Field(default=60, description="默认同步调用超时秒数")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class WorkflowRuntimeInvokeRequestBody(BaseModel):
    """描述 runtime 同步调用请求体。"""

    input_bindings: dict[str, object] = Field(default_factory=dict, description="输入绑定 payload")
    execution_metadata: dict[str, object] = Field(default_factory=dict, description="执行元数据")
    timeout_seconds: int | None = Field(default=None, description="可选同步等待超时秒数")


@workflow_runtime_router.post(
    "/preview-runs",
    response_model=WorkflowPreviewRunContract,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_preview_run(
    body: WorkflowPreviewRunCreateRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowPreviewRunContract:
    """创建并同步执行一次 preview run。"""

    _ensure_project_visible(principal=principal, project_id=body.project_id)
    preview_run = _build_workflow_runtime_service(request).create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id=body.project_id,
            application_ref_id=body.application_ref.application_id if body.application_ref is not None else None,
            application=body.application,
            template=body.template,
            input_bindings=dict(body.input_bindings),
            execution_metadata=_with_created_by(body.execution_metadata, principal.principal_id),
            timeout_seconds=body.timeout_seconds,
        ),
        created_by=principal.principal_id,
    )
    return _build_preview_run_contract(preview_run)


@workflow_runtime_router.get(
    "/preview-runs/{preview_run_id}",
    response_model=WorkflowPreviewRunContract,
)
def get_workflow_preview_run(
    preview_run_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
) -> WorkflowPreviewRunContract:
    """读取一条已保存的 WorkflowPreviewRun。"""

    preview_run = _build_workflow_runtime_service(request).get_preview_run(preview_run_id)
    _ensure_project_visible(principal=principal, project_id=preview_run.project_id)
    return _build_preview_run_contract(preview_run)


@workflow_runtime_router.post(
    "/app-runtimes",
    response_model=WorkflowAppRuntimeContract,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_app_runtime(
    body: WorkflowAppRuntimeCreateRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowAppRuntimeContract:
    """创建一条 WorkflowAppRuntime 记录。"""

    _ensure_project_visible(principal=principal, project_id=body.project_id)
    workflow_app_runtime = _build_workflow_runtime_service(request).create_workflow_app_runtime(
        WorkflowAppRuntimeCreateRequest(
            project_id=body.project_id,
            application_id=body.application_id,
            display_name=body.display_name,
            request_timeout_seconds=body.request_timeout_seconds,
            metadata=dict(body.metadata),
        ),
        created_by=principal.principal_id,
    )
    return _build_workflow_app_runtime_contract(workflow_app_runtime)


@workflow_runtime_router.get(
    "/app-runtimes",
    response_model=list[WorkflowAppRuntimeContract],
)
def list_workflow_app_runtimes(
    project_id: Annotated[str, Query(description="所属 Project id")],
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
) -> list[WorkflowAppRuntimeContract]:
    """按 Project id 列出 WorkflowAppRuntime。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    runtimes = _build_workflow_runtime_service(request).list_workflow_app_runtimes(project_id=project_id)
    return [_build_workflow_app_runtime_contract(item) for item in runtimes]


@workflow_runtime_router.get(
    "/app-runtimes/{workflow_runtime_id}",
    response_model=WorkflowAppRuntimeContract,
)
def get_workflow_app_runtime(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
) -> WorkflowAppRuntimeContract:
    """读取一条 WorkflowAppRuntime。"""

    workflow_app_runtime = _build_workflow_runtime_service(request).get_workflow_app_runtime(workflow_runtime_id)
    _ensure_project_visible(principal=principal, project_id=workflow_app_runtime.project_id)
    return _build_workflow_app_runtime_contract(workflow_app_runtime)


@workflow_runtime_router.post(
    "/app-runtimes/{workflow_runtime_id}/start",
    response_model=WorkflowAppRuntimeContract,
)
def start_workflow_app_runtime(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowAppRuntimeContract:
    """启动一个 WorkflowAppRuntime 对应的 worker。"""

    workflow_app_runtime = _build_workflow_runtime_service(request).get_workflow_app_runtime(workflow_runtime_id)
    _ensure_project_visible(principal=principal, project_id=workflow_app_runtime.project_id)
    updated_runtime = _build_workflow_runtime_service(request).start_workflow_app_runtime(workflow_runtime_id)
    return _build_workflow_app_runtime_contract(updated_runtime)


@workflow_runtime_router.post(
    "/app-runtimes/{workflow_runtime_id}/stop",
    response_model=WorkflowAppRuntimeContract,
)
def stop_workflow_app_runtime(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowAppRuntimeContract:
    """停止一个 WorkflowAppRuntime 对应的 worker。"""

    workflow_app_runtime = _build_workflow_runtime_service(request).get_workflow_app_runtime(workflow_runtime_id)
    _ensure_project_visible(principal=principal, project_id=workflow_app_runtime.project_id)
    updated_runtime = _build_workflow_runtime_service(request).stop_workflow_app_runtime(workflow_runtime_id)
    return _build_workflow_app_runtime_contract(updated_runtime)


@workflow_runtime_router.post(
    "/app-runtimes/{workflow_runtime_id}/restart",
    response_model=WorkflowAppRuntimeContract,
)
def restart_workflow_app_runtime(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowAppRuntimeContract:
    """重启一个 WorkflowAppRuntime 对应的 worker。"""

    workflow_app_runtime = _build_workflow_runtime_service(request).get_workflow_app_runtime(workflow_runtime_id)
    _ensure_project_visible(principal=principal, project_id=workflow_app_runtime.project_id)
    updated_runtime = _build_workflow_runtime_service(request).restart_workflow_app_runtime(workflow_runtime_id)
    return _build_workflow_app_runtime_contract(updated_runtime)


@workflow_runtime_router.get(
    "/app-runtimes/{workflow_runtime_id}/health",
    response_model=WorkflowAppRuntimeContract,
)
def get_workflow_app_runtime_health(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
) -> WorkflowAppRuntimeContract:
    """查询一个 WorkflowAppRuntime 的当前健康状态。"""

    workflow_app_runtime = _build_workflow_runtime_service(request).get_workflow_app_runtime(workflow_runtime_id)
    _ensure_project_visible(principal=principal, project_id=workflow_app_runtime.project_id)
    updated_runtime = _build_workflow_runtime_service(request).get_workflow_app_runtime_health(workflow_runtime_id)
    return _build_workflow_app_runtime_contract(updated_runtime)


@workflow_runtime_router.get(
    "/app-runtimes/{workflow_runtime_id}/instances",
    response_model=list[WorkflowAppRuntimeInstanceContract],
)
def list_workflow_app_runtime_instances(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
) -> list[WorkflowAppRuntimeInstanceContract]:
    """列出一个 WorkflowAppRuntime 当前可观测的 instance。"""

    workflow_app_runtime = _build_workflow_runtime_service(request).get_workflow_app_runtime(workflow_runtime_id)
    _ensure_project_visible(principal=principal, project_id=workflow_app_runtime.project_id)
    instances = _build_workflow_runtime_service(request).list_workflow_app_runtime_instances(workflow_runtime_id)
    return [_build_workflow_app_runtime_instance_contract(item) for item in instances]


@workflow_runtime_router.post(
    "/app-runtimes/{workflow_runtime_id}/runs",
    response_model=WorkflowRunContract,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_run(
    workflow_runtime_id: str,
    body: WorkflowRuntimeInvokeRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowRunContract:
    """为已启动的 runtime 创建一条异步 WorkflowRun。"""

    workflow_app_runtime = _build_workflow_runtime_service(request).get_workflow_app_runtime(workflow_runtime_id)
    _ensure_project_visible(principal=principal, project_id=workflow_app_runtime.project_id)
    workflow_run = _build_workflow_runtime_service(request).create_workflow_run(
        workflow_runtime_id,
        WorkflowRuntimeInvokeRequest(
            input_bindings=dict(body.input_bindings),
            execution_metadata=_with_created_by(body.execution_metadata, principal.principal_id),
            timeout_seconds=body.timeout_seconds,
        ),
        created_by=principal.principal_id,
    )
    return _build_workflow_run_contract(workflow_run)


@workflow_runtime_router.post(
    "/app-runtimes/{workflow_runtime_id}/invoke",
    response_model=WorkflowRunContract,
)
def invoke_workflow_app_runtime(
    workflow_runtime_id: str,
    body: WorkflowRuntimeInvokeRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowRunContract:
    """通过已启动的 runtime 发起一次同步调用。"""

    workflow_app_runtime = _build_workflow_runtime_service(request).get_workflow_app_runtime(workflow_runtime_id)
    _ensure_project_visible(principal=principal, project_id=workflow_app_runtime.project_id)
    workflow_run = _build_workflow_runtime_service(request).invoke_workflow_app_runtime(
        workflow_runtime_id,
        WorkflowRuntimeInvokeRequest(
            input_bindings=dict(body.input_bindings),
            execution_metadata=_with_created_by(body.execution_metadata, principal.principal_id),
            timeout_seconds=body.timeout_seconds,
        ),
        created_by=principal.principal_id,
    )
    return _build_workflow_run_contract(workflow_run)


@workflow_runtime_router.get(
    "/runs/{workflow_run_id}",
    response_model=WorkflowRunContract,
)
def get_workflow_run(
    workflow_run_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
) -> WorkflowRunContract:
    """读取一条 WorkflowRun。"""

    workflow_run = _build_workflow_runtime_service(request).get_workflow_run(workflow_run_id)
    _ensure_project_visible(principal=principal, project_id=workflow_run.project_id)
    return _build_workflow_run_contract(workflow_run)


@workflow_runtime_router.post(
    "/runs/{workflow_run_id}/cancel",
    response_model=WorkflowRunContract,
)
def cancel_workflow_run(
    workflow_run_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowRunContract:
    """取消一条异步 WorkflowRun。"""

    workflow_run = _build_workflow_runtime_service(request).get_workflow_run(workflow_run_id)
    _ensure_project_visible(principal=principal, project_id=workflow_run.project_id)
    updated_run = _build_workflow_runtime_service(request).cancel_workflow_run(
        workflow_run_id,
        cancelled_by=principal.principal_id,
    )
    return _build_workflow_run_contract(updated_run)


def _build_workflow_runtime_service(request: Request) -> WorkflowRuntimeService:
    """基于 application.state 构建 workflow runtime 控制面服务。"""

    return WorkflowRuntimeService(
        settings=_require_backend_service_settings(request),
        session_factory=_require_session_factory(request),
        dataset_storage=_require_dataset_storage(request),
        node_catalog_registry=_require_node_catalog_registry(request),
        worker_manager=_require_workflow_runtime_worker_manager(request),
    )


def _require_backend_service_settings(request: Request) -> BackendServiceSettings:
    """从 application.state 中读取 BackendServiceSettings。"""

    settings = getattr(request.app.state, "backend_service_settings", None)
    if not isinstance(settings, BackendServiceSettings):
        raise ServiceConfigurationError("当前服务尚未完成 backend_service_settings 装配")
    return settings


def _require_session_factory(request: Request) -> SessionFactory:
    """从 application.state 中读取 SessionFactory。"""

    session_factory = getattr(request.app.state, "session_factory", None)
    if not isinstance(session_factory, SessionFactory):
        raise ServiceConfigurationError("当前服务尚未完成 session_factory 装配")
    return session_factory


def _require_dataset_storage(request: Request) -> LocalDatasetStorage:
    """从 application.state 中读取 LocalDatasetStorage。"""

    dataset_storage = getattr(request.app.state, "dataset_storage", None)
    if not isinstance(dataset_storage, LocalDatasetStorage):
        raise ServiceConfigurationError("当前服务尚未完成 dataset_storage 装配")
    return dataset_storage


def _require_node_catalog_registry(request: Request) -> NodeCatalogRegistry:
    """从 application.state 中读取 NodeCatalogRegistry。"""

    node_catalog_registry = getattr(request.app.state, "node_catalog_registry", None)
    if not isinstance(node_catalog_registry, NodeCatalogRegistry):
        raise ServiceConfigurationError("当前服务尚未完成 node_catalog_registry 装配")
    return node_catalog_registry


def _require_workflow_runtime_worker_manager(request: Request) -> WorkflowRuntimeWorkerManager:
    """从 application.state 中读取 WorkflowRuntimeWorkerManager。"""

    worker_manager = getattr(request.app.state, "workflow_runtime_worker_manager", None)
    if not isinstance(worker_manager, WorkflowRuntimeWorkerManager):
        raise ServiceConfigurationError("当前服务尚未完成 workflow_runtime_worker_manager 装配")
    return worker_manager


def _ensure_project_visible(*, principal: AuthenticatedPrincipal, project_id: str) -> None:
    """校验当前主体是否可访问指定 Project。"""

    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": project_id},
        )


def _with_created_by(metadata: dict[str, object], created_by: str) -> dict[str, object]:
    """把 created_by 写入执行元数据。"""

    payload = dict(metadata)
    payload.setdefault("created_by", created_by)
    return payload


def _build_preview_run_contract(preview_run: WorkflowPreviewRun) -> WorkflowPreviewRunContract:
    """把 WorkflowPreviewRun 领域对象转换为公开合同。"""

    return WorkflowPreviewRunContract(
        preview_run_id=preview_run.preview_run_id,
        project_id=preview_run.project_id,
        application_id=preview_run.application_id,
        source_kind=preview_run.source_kind,
        application_snapshot_object_key=preview_run.application_snapshot_object_key,
        template_snapshot_object_key=preview_run.template_snapshot_object_key,
        state=preview_run.state,
        created_at=preview_run.created_at,
        started_at=preview_run.started_at,
        finished_at=preview_run.finished_at,
        created_by=preview_run.created_by,
        timeout_seconds=preview_run.timeout_seconds,
        outputs=dict(preview_run.outputs),
        template_outputs=dict(preview_run.template_outputs),
        node_records=[dict(item) for item in preview_run.node_records],
        error_message=preview_run.error_message,
        retention_until=preview_run.retention_until,
        metadata=dict(preview_run.metadata),
    )


def _build_workflow_app_runtime_contract(workflow_app_runtime: WorkflowAppRuntime) -> WorkflowAppRuntimeContract:
    """把 WorkflowAppRuntime 领域对象转换为公开合同。"""

    return WorkflowAppRuntimeContract(
        workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
        project_id=workflow_app_runtime.project_id,
        application_id=workflow_app_runtime.application_id,
        display_name=workflow_app_runtime.display_name,
        application_snapshot_object_key=workflow_app_runtime.application_snapshot_object_key,
        template_snapshot_object_key=workflow_app_runtime.template_snapshot_object_key,
        desired_state=workflow_app_runtime.desired_state,
        observed_state=workflow_app_runtime.observed_state,
        request_timeout_seconds=workflow_app_runtime.request_timeout_seconds,
        created_at=workflow_app_runtime.created_at,
        updated_at=workflow_app_runtime.updated_at,
        created_by=workflow_app_runtime.created_by,
        last_started_at=workflow_app_runtime.last_started_at,
        last_stopped_at=workflow_app_runtime.last_stopped_at,
        heartbeat_at=workflow_app_runtime.heartbeat_at,
        worker_process_id=workflow_app_runtime.worker_process_id,
        loaded_snapshot_fingerprint=workflow_app_runtime.loaded_snapshot_fingerprint,
        last_error=workflow_app_runtime.last_error,
        health_summary=dict(workflow_app_runtime.health_summary),
        metadata=dict(workflow_app_runtime.metadata),
    )


def _build_workflow_run_contract(workflow_run: WorkflowRun) -> WorkflowRunContract:
    """把 WorkflowRun 领域对象转换为公开合同。"""

    return WorkflowRunContract(
        workflow_run_id=workflow_run.workflow_run_id,
        workflow_runtime_id=workflow_run.workflow_runtime_id,
        project_id=workflow_run.project_id,
        application_id=workflow_run.application_id,
        state=workflow_run.state,
        created_at=workflow_run.created_at,
        started_at=workflow_run.started_at,
        finished_at=workflow_run.finished_at,
        created_by=workflow_run.created_by,
        requested_timeout_seconds=workflow_run.requested_timeout_seconds,
        assigned_process_id=workflow_run.assigned_process_id,
        input_payload=dict(workflow_run.input_payload),
        outputs=dict(workflow_run.outputs),
        template_outputs=dict(workflow_run.template_outputs),
        node_records=[dict(item) for item in workflow_run.node_records],
        error_message=workflow_run.error_message,
        metadata=dict(workflow_run.metadata),
    )


def _build_workflow_app_runtime_instance_contract(
    runtime_instance: object,
) -> WorkflowAppRuntimeInstanceContract:
    """把 runtime instance 摘要转换为公开合同。"""

    return WorkflowAppRuntimeInstanceContract(
        instance_id=str(getattr(runtime_instance, "instance_id", "")),
        workflow_runtime_id=str(getattr(runtime_instance, "workflow_runtime_id", "")),
        state=str(getattr(runtime_instance, "state", "")),
        process_id=getattr(runtime_instance, "process_id", None),
        current_run_id=getattr(runtime_instance, "current_run_id", None),
        started_at=getattr(runtime_instance, "started_at", None),
        heartbeat_at=getattr(runtime_instance, "heartbeat_at", None),
        loaded_snapshot_fingerprint=getattr(runtime_instance, "loaded_snapshot_fingerprint", None),
        last_error=getattr(runtime_instance, "last_error", None),
        health_summary=dict(getattr(runtime_instance, "health_summary", {}) or {}),
    )