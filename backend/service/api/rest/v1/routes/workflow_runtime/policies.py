"""workflow runtime execution policy 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from backend.contracts.workflows import WorkflowExecutionPolicyContract
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.rest.v1.pagination import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, paginate_sequence
from backend.service.api.rest.v1.routes.workflow_runtime_support.responses import (
    build_execution_policy_contract as _build_execution_policy_contract,
)
from backend.service.api.rest.v1.routes.workflow_runtime_support.schemas import (
    WorkflowExecutionPolicyCreateRequestBody,
)
from backend.service.api.rest.v1.routes.workflow_runtime_support.services import (
    build_workflow_runtime_service as _build_workflow_runtime_service,
    ensure_project_visible as _ensure_project_visible,
)
from backend.service.application.workflows.runtime.policies import WorkflowExecutionPolicyCreateRequest


workflow_runtime_policies_router = APIRouter()

@workflow_runtime_policies_router.post(
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


@workflow_runtime_policies_router.get(
    "/execution-policies",
    response_model=list[WorkflowExecutionPolicyContract],
)
def list_workflow_execution_policies(
    project_id: Annotated[str, Query(description="所属 Project id")],
    request: Request,
    response: Response,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    offset: Annotated[int, Query(ge=0, description="结果偏移量")] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT, description="最大返回数量")] = DEFAULT_LIST_LIMIT,
) -> list[WorkflowExecutionPolicyContract]:
    """按 Project id 列出 WorkflowExecutionPolicy。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    execution_policies = _build_workflow_runtime_service(request).list_execution_policies(project_id=project_id)
    paged_items = paginate_sequence(execution_policies, response=response, offset=offset, limit=limit)
    return [_build_execution_policy_contract(item) for item in paged_items]


@workflow_runtime_policies_router.get(
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
