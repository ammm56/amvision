"""WorkflowTriggerSource REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from backend.contracts.workflows import WorkflowTriggerSourceContract
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.rest.v1.pagination import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    paginate_sequence,
)
from backend.service.api.rest.v1.routes.workflow_trigger_sources.health import (
    WorkflowTriggerSourceHealthResponse,
    build_trigger_source_health_response,
)
from backend.service.api.rest.v1.routes.workflow_trigger_sources.responses import (
    build_trigger_source_contract,
)
from backend.service.api.rest.v1.routes.workflow_trigger_sources.schemas import (
    WorkflowTriggerSourceCreateRequestBody,
)
from backend.service.api.rest.v1.routes.workflow_trigger_sources.services import (
    build_trigger_source_service,
    ensure_project_visible,
)
from backend.service.application.workflows.trigger_sources import (
    WorkflowTriggerSourceCreateRequest,
)


workflow_trigger_sources_router = APIRouter(
    prefix="/workflows/trigger-sources", tags=["workflow-trigger-sources"]
)


@workflow_trigger_sources_router.post(
    "",
    response_model=WorkflowTriggerSourceContract,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_trigger_source(
    body: WorkflowTriggerSourceCreateRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowTriggerSourceContract:
    """创建一条 WorkflowTriggerSource。"""

    ensure_project_visible(principal=principal, project_id=body.project_id)
    trigger_source = build_trigger_source_service(request).create_trigger_source(
        WorkflowTriggerSourceCreateRequest(
            trigger_source_id=body.trigger_source_id,
            project_id=body.project_id,
            display_name=body.display_name,
            trigger_kind=body.trigger_kind,
            workflow_runtime_id=body.workflow_runtime_id,
            submit_mode=body.submit_mode,
            enabled=body.enabled,
            transport_config=dict(body.transport_config),
            match_rule=dict(body.match_rule),
            input_binding_mapping=dict(body.input_binding_mapping),
            result_mapping=dict(body.result_mapping),
            default_execution_metadata=dict(body.default_execution_metadata),
            ack_policy=body.ack_policy,
            result_mode=body.result_mode,
            reply_timeout_seconds=body.reply_timeout_seconds,
            debounce_window_ms=body.debounce_window_ms,
            idempotency_key_path=body.idempotency_key_path,
            metadata=dict(body.metadata),
        ),
        created_by=principal.principal_id,
    )
    return build_trigger_source_contract(trigger_source, request=request)


@workflow_trigger_sources_router.get(
    "", response_model=list[WorkflowTriggerSourceContract]
)
def list_workflow_trigger_sources(
    project_id: Annotated[str, Query(description="所属 Project id")],
    request: Request,
    response: Response,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
    offset: Annotated[int, Query(ge=0, description="结果偏移量")] = 0,
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIST_LIMIT, description="最大返回数量")
    ] = DEFAULT_LIST_LIMIT,
) -> list[WorkflowTriggerSourceContract]:
    """按 Project id 列出 WorkflowTriggerSource。"""

    ensure_project_visible(principal=principal, project_id=project_id)
    trigger_sources = build_trigger_source_service(request).list_trigger_sources(
        project_id=project_id
    )
    paged_items = paginate_sequence(
        trigger_sources, response=response, offset=offset, limit=limit
    )
    return [
        build_trigger_source_contract(item, request=request) for item in paged_items
    ]


@workflow_trigger_sources_router.get(
    "/{trigger_source_id}", response_model=WorkflowTriggerSourceContract
)
def get_workflow_trigger_source(
    trigger_source_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
) -> WorkflowTriggerSourceContract:
    """读取一条 WorkflowTriggerSource。"""

    trigger_source = build_trigger_source_service(request).get_trigger_source(
        trigger_source_id
    )
    ensure_project_visible(principal=principal, project_id=trigger_source.project_id)
    return build_trigger_source_contract(trigger_source, request=request)


@workflow_trigger_sources_router.post(
    "/{trigger_source_id}/enable", response_model=WorkflowTriggerSourceContract
)
def enable_workflow_trigger_source(
    trigger_source_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowTriggerSourceContract:
    """启用一条 WorkflowTriggerSource。"""

    trigger_source_service = build_trigger_source_service(request)
    current_trigger_source = trigger_source_service.get_trigger_source(
        trigger_source_id
    )
    ensure_project_visible(
        principal=principal, project_id=current_trigger_source.project_id
    )
    trigger_source = trigger_source_service.enable_trigger_source(
        trigger_source_id,
        updated_by=principal.principal_id,
    )
    return build_trigger_source_contract(trigger_source, request=request)


@workflow_trigger_sources_router.post(
    "/{trigger_source_id}/disable", response_model=WorkflowTriggerSourceContract
)
def disable_workflow_trigger_source(
    trigger_source_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowTriggerSourceContract:
    """停用一条 WorkflowTriggerSource。"""

    trigger_source_service = build_trigger_source_service(request)
    current_trigger_source = trigger_source_service.get_trigger_source(
        trigger_source_id
    )
    ensure_project_visible(
        principal=principal, project_id=current_trigger_source.project_id
    )
    trigger_source = trigger_source_service.disable_trigger_source(
        trigger_source_id,
        updated_by=principal.principal_id,
    )
    return build_trigger_source_contract(trigger_source, request=request)


@workflow_trigger_sources_router.delete(
    "/{trigger_source_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_workflow_trigger_source(
    trigger_source_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> Response:
    """删除一条 WorkflowTriggerSource。"""

    trigger_source_service = build_trigger_source_service(request)
    current_trigger_source = trigger_source_service.get_trigger_source(
        trigger_source_id
    )
    ensure_project_visible(
        principal=principal, project_id=current_trigger_source.project_id
    )
    trigger_source_service.delete_trigger_source(trigger_source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@workflow_trigger_sources_router.get(
    "/{trigger_source_id}/health",
    response_model=WorkflowTriggerSourceHealthResponse,
)
def get_workflow_trigger_source_health(
    trigger_source_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
) -> WorkflowTriggerSourceHealthResponse:
    """读取一条 WorkflowTriggerSource 的健康摘要。"""

    trigger_source_service = build_trigger_source_service(request)
    trigger_source = trigger_source_service.get_trigger_source(trigger_source_id)
    ensure_project_visible(principal=principal, project_id=trigger_source.project_id)
    return build_trigger_source_health_response(
        trigger_source_service.get_trigger_source_health(trigger_source_id)
    )

