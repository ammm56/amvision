"""workflow runtime run 和 invoke 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from backend.contracts.workflows import WorkflowRunContract, WorkflowRunEventContract
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.rest.v1.routes.workflow_runtime_support.responses import (
    build_workflow_run_contract as _build_workflow_run_contract,
    build_workflow_run_event_contract as _build_workflow_run_event_contract,
)
from backend.service.api.rest.v1.routes.workflow_runtime_support.schemas import WorkflowRuntimeInvokeRequestBody
from backend.service.api.rest.v1.routes.workflow_runtime_support.services import (
    build_workflow_runtime_service as _build_workflow_runtime_service,
    ensure_project_visible as _ensure_project_visible,
    with_created_by as _with_created_by,
)
from backend.service.api.rest.v1.routes.workflow_runtime_support.uploads import (
    build_multipart_runtime_invoke_request as _build_multipart_runtime_invoke_request,
)
from backend.service.application.workflows.runtime.invokes import WorkflowRuntimeInvokeRequest


workflow_runtime_runs_router = APIRouter()

@workflow_runtime_runs_router.post(
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


@workflow_runtime_runs_router.post(
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


@workflow_runtime_runs_router.post(
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
    invoke_result = _build_workflow_runtime_service(request).invoke_workflow_app_runtime_with_response(
        workflow_runtime_id,
        WorkflowRuntimeInvokeRequest(
            input_bindings=dict(body.input_bindings),
            execution_metadata=_with_created_by(body.execution_metadata, principal.principal_id),
            timeout_seconds=body.timeout_seconds,
        ),
        created_by=principal.principal_id,
    )
    return _build_workflow_run_contract(
        invoke_result.workflow_run,
        outputs=invoke_result.raw_outputs,
        template_outputs=invoke_result.raw_template_outputs,
        node_records=invoke_result.raw_node_records,
    )


@workflow_runtime_runs_router.post(
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
    invoke_result = _build_workflow_runtime_service(request).invoke_workflow_app_runtime_with_response(
        workflow_runtime_id,
        invoke_request,
        created_by=principal.principal_id,
    )
    return _build_workflow_run_contract(
        invoke_result.workflow_run,
        outputs=invoke_result.raw_outputs,
        template_outputs=invoke_result.raw_template_outputs,
        node_records=invoke_result.raw_node_records,
    )


@workflow_runtime_runs_router.get(
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


@workflow_runtime_runs_router.get(
    "/runs/{workflow_run_id}/events",
    response_model=list[WorkflowRunEventContract],
)
def get_workflow_run_events(
    workflow_run_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    after_sequence: Annotated[int | None, Query(description="只返回 sequence 大于该值的事件", ge=0)] = None,
    limit: Annotated[int | None, Query(description="最多返回多少条事件", ge=1, le=500)] = None,
) -> list[WorkflowRunEventContract]:
    """读取一条 WorkflowRun 的事件列表。"""

    runtime_service = _build_workflow_runtime_service(request)
    workflow_run = runtime_service.get_workflow_run(workflow_run_id)
    _ensure_project_visible(principal=principal, project_id=workflow_run.project_id)
    events = runtime_service.get_workflow_run_events(
        workflow_run_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return [_build_workflow_run_event_contract(item) for item in events]


@workflow_runtime_runs_router.post(
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


