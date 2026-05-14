"""workflow runtime 控制面 REST 路由。"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from backend.contracts.workflows import (
    FlowApplication,
    WorkflowAppRuntimeInstanceContract,
    WorkflowAppRuntimeContract,
    WorkflowExecutionPolicyContract,
    WorkflowGraphTemplate,
    WorkflowPreviewRunContract,
    WorkflowPreviewRunSummaryContract,
    WorkflowRunContract,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError, ServiceConfigurationError
from backend.service.application.deployments import PublishedInferenceGateway
from backend.service.application.local_buffers import LocalBufferBrokerEventChannel, LocalBufferBrokerProcessSupervisor
from backend.service.application.workflows.runtime_service import (
    WorkflowAppRuntimeCreateRequest,
    WorkflowExecutionPolicyCreateRequest,
    WorkflowPreviewRunCreateRequest,
    WorkflowRuntimeInvokeRequest,
    WorkflowRuntimeService,
)
from backend.service.application.workflows.runtime_worker import WorkflowRuntimeWorkerManager
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowExecutionPolicy,
    WorkflowPreviewRun,
    WorkflowRun,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import BackendServiceSettings


workflow_runtime_router = APIRouter(prefix="/workflows", tags=["workflow-runtime"])


_MULTIPART_RUNTIME_RESERVED_FIELDS = frozenset(
    {
        "input_bindings_json",
        "input_bindings",
        "execution_metadata_json",
        "execution_metadata",
        "timeout_seconds",
    }
)


class WorkflowApplicationRefRequestBody(BaseModel):
    """描述 preview run 请求体里的 application 引用。"""

    application_id: str = Field(description="已保存 FlowApplication id")


class WorkflowPreviewRunCreateRequestBody(BaseModel):
    """描述 preview run 创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    execution_policy_id: str | None = Field(default=None, description="可选的 WorkflowExecutionPolicy id")
    application_ref: WorkflowApplicationRefRequestBody | None = Field(
        default=None,
        description="可选的已保存 application 引用",
    )
    application: FlowApplication | None = Field(default=None, description="可选 inline application snapshot")
    template: WorkflowGraphTemplate | None = Field(default=None, description="可选 inline template snapshot")
    input_bindings: dict[str, object] = Field(default_factory=dict, description="输入绑定 payload")
    execution_metadata: dict[str, object] = Field(default_factory=dict, description="执行元数据")
    timeout_seconds: int | None = Field(default=None, description="可选同步等待超时秒数")


class WorkflowExecutionPolicyCreateRequestBody(BaseModel):
    """描述 WorkflowExecutionPolicy 创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    execution_policy_id: str = Field(description="策略 id")
    display_name: str = Field(description="展示名称")
    policy_kind: str = Field(description="策略类型")
    default_timeout_seconds: int = Field(default=30, description="默认执行超时秒数")
    max_run_timeout_seconds: int = Field(default=30, description="最大执行超时秒数")
    trace_level: str = Field(default="node-summary", description="trace 保留级别")
    retain_node_records_enabled: bool = Field(default=True, description="是否保留 node_records")
    retain_trace_enabled: bool = Field(default=True, description="是否保留 trace 数据")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class WorkflowAppRuntimeCreateRequestBody(BaseModel):
    """描述 app runtime 创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    application_id: str = Field(description="已保存 FlowApplication id")
    execution_policy_id: str | None = Field(default=None, description="可选的 WorkflowExecutionPolicy id")
    display_name: str = Field(default="", description="可选展示名称")
    request_timeout_seconds: int | None = Field(default=None, description="可选默认同步调用超时秒数")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


@workflow_runtime_router.post(
    "/execution-policies",
    response_model=WorkflowExecutionPolicyContract,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_execution_policy(
    body: WorkflowExecutionPolicyCreateRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowExecutionPolicyContract:
    """创建一条 WorkflowExecutionPolicy。"""

    _ensure_project_visible(principal=principal, project_id=body.project_id)
    execution_policy = _build_workflow_runtime_service(request).create_execution_policy(
        WorkflowExecutionPolicyCreateRequest(
            project_id=body.project_id,
            execution_policy_id=body.execution_policy_id,
            display_name=body.display_name,
            policy_kind=body.policy_kind,
            default_timeout_seconds=body.default_timeout_seconds,
            max_run_timeout_seconds=body.max_run_timeout_seconds,
            trace_level=body.trace_level,
            retain_node_records_enabled=body.retain_node_records_enabled,
            retain_trace_enabled=body.retain_trace_enabled,
            metadata=dict(body.metadata),
        ),
        created_by=principal.principal_id,
    )
    return _build_execution_policy_contract(execution_policy)


@workflow_runtime_router.get(
    "/execution-policies",
    response_model=list[WorkflowExecutionPolicyContract],
)
def list_workflow_execution_policies(
    project_id: Annotated[str, Query(description="所属 Project id")],
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
) -> list[WorkflowExecutionPolicyContract]:
    """按 Project id 列出 WorkflowExecutionPolicy。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    execution_policies = _build_workflow_runtime_service(request).list_execution_policies(project_id=project_id)
    return [_build_execution_policy_contract(item) for item in execution_policies]


@workflow_runtime_router.get(
    "/execution-policies/{execution_policy_id}",
    response_model=WorkflowExecutionPolicyContract,
)
def get_workflow_execution_policy(
    execution_policy_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
) -> WorkflowExecutionPolicyContract:
    """读取一条 WorkflowExecutionPolicy。"""

    execution_policy = _build_workflow_runtime_service(request).get_execution_policy(execution_policy_id)
    _ensure_project_visible(principal=principal, project_id=execution_policy.project_id)
    return _build_execution_policy_contract(execution_policy)


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
    preview_run = _build_workflow_runtime_service(
        request,
        include_local_buffer_broker_event_channel=True,
    ).create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id=body.project_id,
            application_ref_id=body.application_ref.application_id if body.application_ref is not None else None,
            execution_policy_id=body.execution_policy_id,
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
    "/preview-runs",
    response_model=list[WorkflowPreviewRunSummaryContract],
)
def list_workflow_preview_runs(
    project_id: Annotated[str, Query(description="所属 Project id")],
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    state: Annotated[str | None, Query(description="按 preview run 状态过滤")] = None,
    created_from: Annotated[str | None, Query(description="按 created_at 下界过滤，ISO8601")]= None,
    created_to: Annotated[str | None, Query(description="按 created_at 上界过滤，ISO8601")] = None,
) -> list[WorkflowPreviewRunSummaryContract]:
    """按 Project id、状态和创建时间范围列出 WorkflowPreviewRun 摘要。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    preview_runs = _build_workflow_runtime_service(request).list_preview_runs_filtered(
        project_id=project_id,
        state=state,
        created_from=created_from,
        created_to=created_to,
    )
    return [_build_preview_run_summary_contract(item) for item in preview_runs]


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


@workflow_runtime_router.delete(
    "/preview-runs/{preview_run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_workflow_preview_run(
    preview_run_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> Response:
    """删除一条 WorkflowPreviewRun 及其 snapshot 目录。"""

    preview_run = _build_workflow_runtime_service(request).get_preview_run(preview_run_id)
    _ensure_project_visible(principal=principal, project_id=preview_run.project_id)
    _build_workflow_runtime_service(request).delete_preview_run(preview_run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
            execution_policy_id=body.execution_policy_id,
            display_name=body.display_name,
            request_timeout_seconds=body.request_timeout_seconds,
            metadata=dict(body.metadata),
        ),
        created_by=principal.principal_id,
    )
    return _build_workflow_app_runtime_contract(
        workflow_app_runtime,
        workflow_service=_build_workflow_json_service_from_request(request),
    )


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
    workflow_service = _build_workflow_json_service_from_request(request)
    return [
        _build_workflow_app_runtime_contract(item, workflow_service=workflow_service)
        for item in runtimes
    ]


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
    return _build_workflow_app_runtime_contract(
        workflow_app_runtime,
        workflow_service=_build_workflow_json_service_from_request(request),
    )


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
    updated_runtime = _build_workflow_runtime_service(request).start_workflow_app_runtime(
        workflow_runtime_id,
        updated_by=principal.principal_id,
    )
    return _build_workflow_app_runtime_contract(
        updated_runtime,
        workflow_service=_build_workflow_json_service_from_request(request),
    )


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
    updated_runtime = _build_workflow_runtime_service(request).stop_workflow_app_runtime(
        workflow_runtime_id,
        updated_by=principal.principal_id,
    )
    return _build_workflow_app_runtime_contract(
        updated_runtime,
        workflow_service=_build_workflow_json_service_from_request(request),
    )


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
    updated_runtime = _build_workflow_runtime_service(request).restart_workflow_app_runtime(
        workflow_runtime_id,
        updated_by=principal.principal_id,
    )
    return _build_workflow_app_runtime_contract(
        updated_runtime,
        workflow_service=_build_workflow_json_service_from_request(request),
    )


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
    return _build_workflow_app_runtime_contract(
        updated_runtime,
        workflow_service=_build_workflow_json_service_from_request(request),
    )


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
    "/app-runtimes/{workflow_runtime_id}/runs/upload",
    response_model=WorkflowRunContract,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow_run_upload(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowRunContract:
    """为已启动的 runtime 创建一条支持 multipart 上传的异步 WorkflowRun。"""

    workflow_app_runtime = _build_workflow_runtime_service(request).get_workflow_app_runtime(workflow_runtime_id)
    _ensure_project_visible(principal=principal, project_id=workflow_app_runtime.project_id)
    invoke_request = await _build_multipart_runtime_invoke_request(
        request=request,
        workflow_app_runtime=workflow_app_runtime,
        created_by=principal.principal_id,
    )
    workflow_run = _build_workflow_runtime_service(request).create_workflow_run(
        workflow_runtime_id,
        invoke_request,
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


@workflow_runtime_router.post(
    "/app-runtimes/{workflow_runtime_id}/invoke/upload",
    response_model=WorkflowRunContract,
)
async def invoke_workflow_app_runtime_upload(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowRunContract:
    """通过 multipart 上传方式发起一次同步 workflow 调用。"""

    workflow_app_runtime = _build_workflow_runtime_service(request).get_workflow_app_runtime(workflow_runtime_id)
    _ensure_project_visible(principal=principal, project_id=workflow_app_runtime.project_id)
    invoke_request = await _build_multipart_runtime_invoke_request(
        request=request,
        workflow_app_runtime=workflow_app_runtime,
        created_by=principal.principal_id,
    )
    workflow_run = _build_workflow_runtime_service(request).invoke_workflow_app_runtime(
        workflow_runtime_id,
        invoke_request,
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


def _build_workflow_runtime_service(
    request: Request,
    *,
    include_local_buffer_broker_event_channel: bool = False,
) -> WorkflowRuntimeService:
    """基于 application.state 构建 workflow runtime 控制面服务。"""

    return WorkflowRuntimeService(
        settings=_require_backend_service_settings(request),
        session_factory=_require_session_factory(request),
        dataset_storage=_require_dataset_storage(request),
        node_catalog_registry=_require_node_catalog_registry(request),
        worker_manager=_require_workflow_runtime_worker_manager(request),
        local_buffer_broker_event_channel=(
            _read_local_buffer_broker_event_channel(request)
            if include_local_buffer_broker_event_channel
            else None
        ),
        published_inference_gateway=_read_published_inference_gateway(request),
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


def _read_local_buffer_broker_event_channel(request: Request) -> LocalBufferBrokerEventChannel | None:
    """从 application.state 中读取 LocalBufferBroker 事件通道。"""

    supervisor = getattr(request.app.state, "local_buffer_broker_supervisor", None)
    if supervisor is None:
        return None
    if not isinstance(supervisor, LocalBufferBrokerProcessSupervisor):
        raise ServiceConfigurationError("当前服务 local_buffer_broker_supervisor 装配无效")
    return supervisor.get_event_channel()


def _read_published_inference_gateway(request: Request) -> PublishedInferenceGateway | None:
    """从 application.state 中读取父进程 PublishedInferenceGateway。"""

    gateway = getattr(request.app.state, "published_inference_gateway", None)
    if gateway is None:
        return None
    if not callable(getattr(gateway, "infer", None)):
        raise ServiceConfigurationError("当前服务 published_inference_gateway 装配无效")
    return gateway


def _ensure_project_visible(*, principal: AuthenticatedPrincipal, project_id: str) -> None:
    """校验当前主体是否可访问指定 Project。"""

    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": project_id},
        )


def _build_workflow_json_service_from_request(request: Request) -> LocalWorkflowJsonService:
    """基于 application.state 构建 workflow authoring 文件服务。"""

    return LocalWorkflowJsonService(
        dataset_storage=_require_dataset_storage(request),
        node_catalog_registry=_require_node_catalog_registry(request),
    )


def _with_created_by(metadata: dict[str, object], created_by: str) -> dict[str, object]:
    """把 created_by 写入执行元数据。"""

    payload = dict(metadata)
    payload.setdefault("created_by", created_by)
    return payload


async def _build_multipart_runtime_invoke_request(
    *,
    request: Request,
    workflow_app_runtime: WorkflowAppRuntime,
    created_by: str,
) -> WorkflowRuntimeInvokeRequest:
    """把 multipart/form-data 请求转换为 workflow runtime 调用请求。"""

    form = await request.form()
    input_bindings = _read_optional_json_object(
        form.get("input_bindings_json") or form.get("input_bindings"),
        field_name="input_bindings_json",
    )
    execution_metadata = _with_created_by(
        _read_optional_json_object(
            form.get("execution_metadata_json") or form.get("execution_metadata"),
            field_name="execution_metadata_json",
        ),
        created_by,
    )
    timeout_seconds = _read_optional_int_text(
        form.get("timeout_seconds"),
        field_name="timeout_seconds",
    )
    application = _load_runtime_application(request=request, workflow_app_runtime=workflow_app_runtime)
    input_binding_payload_types = {
        binding.binding_id: str(
            binding.config.get("payload_type_id")
            or binding.metadata.get("payload_type_id")
            or ""
        )
        for binding in application.bindings
        if binding.direction == "input"
    }
    for field_name, field_value in form.multi_items():
        if field_name in _MULTIPART_RUNTIME_RESERVED_FIELDS:
            continue
        if isinstance(field_value, UploadFile):
            if field_name in input_bindings:
                raise InvalidRequestError(
                    "multipart 上传字段与 input_bindings_json 中的 binding_id 冲突",
                    details={"binding_id": field_name},
                )
            payload_type_id = input_binding_payload_types.get(field_name)
            if payload_type_id is None:
                raise InvalidRequestError(
                    "multipart 上传字段未声明为 workflow application 输入绑定",
                    details={"binding_id": field_name},
                )
            if payload_type_id != "dataset-package.v1":
                raise InvalidRequestError(
                    "当前 multipart 上传入口仅支持 dataset-package.v1 输入绑定",
                    details={"binding_id": field_name, "payload_type_id": payload_type_id},
                )
            input_bindings[field_name] = await _build_dataset_package_binding_payload(
                upload=field_value,
                binding_id=field_name,
            )
            continue
        raise InvalidRequestError(
            "multipart 非文件字段请放入 input_bindings_json 或 execution_metadata_json",
            details={"field_name": field_name},
        )
    return WorkflowRuntimeInvokeRequest(
        input_bindings=input_bindings,
        execution_metadata=execution_metadata,
        timeout_seconds=timeout_seconds,
    )


async def _build_dataset_package_binding_payload(
    *,
    upload: UploadFile,
    binding_id: str,
) -> dict[str, object]:
    """把上传文件转换为 DatasetImport 节点消费的 payload。"""

    package_bytes = await upload.read()
    file_name = upload.filename.strip() if isinstance(upload.filename, str) and upload.filename.strip() else "dataset.zip"
    if not package_bytes:
        raise InvalidRequestError(
            "上传数据集 zip 不能为空",
            details={"binding_id": binding_id, "file_name": file_name},
        )
    payload: dict[str, object] = {
        "package_file_name": file_name,
        "package_bytes": package_bytes,
    }
    if isinstance(upload.content_type, str) and upload.content_type.strip():
        payload["media_type"] = upload.content_type.strip()
    return payload


def _load_runtime_application(
    *,
    request: Request,
    workflow_app_runtime: WorkflowAppRuntime,
) -> FlowApplication:
    """读取指定 runtime 绑定的 FlowApplication。"""

    workflow_service = LocalWorkflowJsonService(
        dataset_storage=_require_dataset_storage(request),
        node_catalog_registry=_require_node_catalog_registry(request),
    )
    return workflow_service.get_application(
        project_id=workflow_app_runtime.project_id,
        application_id=workflow_app_runtime.application_id,
    ).application


def _read_optional_json_object(value: object, *, field_name: str) -> dict[str, object]:
    """把可选的 JSON 文本字段解析为对象。"""

    if value is None:
        return {}
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(
            "multipart JSON 字段必须是非空字符串",
            details={"field_name": field_name},
        )
    try:
        parsed_value = json.loads(value)
    except json.JSONDecodeError as exc:
        raise InvalidRequestError(
            "multipart JSON 字段不是有效 JSON",
            details={"field_name": field_name},
        ) from exc
    if not isinstance(parsed_value, dict):
        raise InvalidRequestError(
            "multipart JSON 字段必须是对象",
            details={"field_name": field_name},
        )
    return {str(key): item for key, item in parsed_value.items()}


def _read_optional_int_text(value: object, *, field_name: str) -> int | None:
    """把可选字符串字段解析为整数。"""

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(
            "multipart 整数字段必须是非空字符串",
            details={"field_name": field_name},
        )
    try:
        normalized_value = int(value.strip())
    except ValueError as exc:
        raise InvalidRequestError(
            "multipart 整数字段不是有效整数",
            details={"field_name": field_name},
        ) from exc
    return normalized_value


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


def _build_preview_run_summary_contract(
    preview_run: WorkflowPreviewRun,
) -> WorkflowPreviewRunSummaryContract:
    """把 WorkflowPreviewRun 领域对象转换为摘要合同。"""

    return WorkflowPreviewRunSummaryContract(
        preview_run_id=preview_run.preview_run_id,
        project_id=preview_run.project_id,
        application_id=preview_run.application_id,
        source_kind=preview_run.source_kind,
        state=preview_run.state,
        created_at=preview_run.created_at,
        started_at=preview_run.started_at,
        finished_at=preview_run.finished_at,
        created_by=preview_run.created_by,
        timeout_seconds=preview_run.timeout_seconds,
        error_message=preview_run.error_message,
        retention_until=preview_run.retention_until,
    )


def _build_workflow_app_runtime_contract(
    workflow_app_runtime: WorkflowAppRuntime,
    *,
    workflow_service: LocalWorkflowJsonService | None = None,
) -> WorkflowAppRuntimeContract:
    """把 WorkflowAppRuntime 领域对象转换为公开合同。"""

    application_summary = None
    template_summary = None
    if workflow_service is not None:
        application_summary = _try_build_application_reference_summary_contract(
            workflow_service=workflow_service,
            project_id=workflow_app_runtime.project_id,
            application_id=workflow_app_runtime.application_id,
        )
        if application_summary is not None:
            template_summary = _try_build_template_reference_summary_contract(
                workflow_service=workflow_service,
                project_id=application_summary["project_id"],
                template_id=application_summary["template_id"],
                template_version=application_summary["template_version"],
            )

    return WorkflowAppRuntimeContract(
        workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
        project_id=workflow_app_runtime.project_id,
        application_id=workflow_app_runtime.application_id,
        display_name=workflow_app_runtime.display_name,
        application_snapshot_object_key=workflow_app_runtime.application_snapshot_object_key,
        template_snapshot_object_key=workflow_app_runtime.template_snapshot_object_key,
        execution_policy_snapshot_object_key=workflow_app_runtime.execution_policy_snapshot_object_key,
        desired_state=workflow_app_runtime.desired_state,
        observed_state=workflow_app_runtime.observed_state,
        request_timeout_seconds=workflow_app_runtime.request_timeout_seconds,
        created_at=workflow_app_runtime.created_at,
        updated_at=workflow_app_runtime.updated_at,
        created_by=workflow_app_runtime.created_by,
        updated_by=_read_resource_updated_by(workflow_app_runtime.metadata),
        application_summary=application_summary,
        template_summary=template_summary,
        last_started_at=workflow_app_runtime.last_started_at,
        last_stopped_at=workflow_app_runtime.last_stopped_at,
        heartbeat_at=workflow_app_runtime.heartbeat_at,
        worker_process_id=workflow_app_runtime.worker_process_id,
        loaded_snapshot_fingerprint=workflow_app_runtime.loaded_snapshot_fingerprint,
        last_error=workflow_app_runtime.last_error,
        health_summary=dict(workflow_app_runtime.health_summary),
        metadata=dict(workflow_app_runtime.metadata),
    )


def _try_build_application_reference_summary_contract(
    *,
    workflow_service: LocalWorkflowJsonService,
    project_id: str,
    application_id: str,
) -> dict[str, object] | None:
    """按需读取 application 一跳摘要，不存在时返回 None。"""

    try:
        summary = workflow_service.get_application_summary(
            project_id=project_id,
            application_id=application_id,
        )
    except ResourceNotFoundError:
        return None
    return {
        "project_id": summary.project_id,
        "application_id": summary.application_id,
        "display_name": summary.display_name,
        "description": summary.description,
        "created_at": summary.created_at,
        "updated_at": summary.updated_at,
        "created_by": summary.created_by,
        "updated_by": summary.updated_by,
        "template_id": summary.template_id,
        "template_version": summary.template_version,
    }


def _try_build_template_reference_summary_contract(
    *,
    workflow_service: LocalWorkflowJsonService,
    project_id: str,
    template_id: str,
    template_version: str,
) -> dict[str, object] | None:
    """按需读取 template 一跳摘要，不存在时返回 None。"""

    try:
        summary = workflow_service.get_template_version_summary(
            project_id=project_id,
            template_id=template_id,
            template_version=template_version,
        )
    except ResourceNotFoundError:
        return None
    return {
        "project_id": summary.project_id,
        "template_id": summary.template_id,
        "template_version": summary.template_version,
        "display_name": summary.display_name,
        "description": summary.description,
        "created_at": summary.created_at,
        "updated_at": summary.updated_at,
        "created_by": summary.created_by,
        "updated_by": summary.updated_by,
    }


def _read_resource_updated_by(metadata: dict[str, object]) -> str | None:
    """从资源 metadata 中读取最近修改主体。"""

    updated_by = metadata.get("updated_by")
    if not isinstance(updated_by, str):
        return None
    normalized_updated_by = updated_by.strip()
    return normalized_updated_by or None


def _build_execution_policy_contract(execution_policy: WorkflowExecutionPolicy) -> WorkflowExecutionPolicyContract:
    """把 WorkflowExecutionPolicy 领域对象转换为公开合同。"""

    return WorkflowExecutionPolicyContract(
        execution_policy_id=execution_policy.execution_policy_id,
        project_id=execution_policy.project_id,
        display_name=execution_policy.display_name,
        policy_kind=execution_policy.policy_kind,
        default_timeout_seconds=execution_policy.default_timeout_seconds,
        max_run_timeout_seconds=execution_policy.max_run_timeout_seconds,
        trace_level=execution_policy.trace_level,
        retain_node_records_enabled=execution_policy.retain_node_records_enabled,
        retain_trace_enabled=execution_policy.retain_trace_enabled,
        created_at=execution_policy.created_at,
        updated_at=execution_policy.updated_at,
        created_by=execution_policy.created_by,
        metadata=dict(execution_policy.metadata),
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