"""workflow app runtime 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from backend.contracts.workflows import (
    WorkflowAppRuntimeContract,
    WorkflowAppRuntimeEventContract,
    WorkflowAppRuntimeInstanceContract,
    WorkflowRuntimeRevisionContract,
)
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.rest.v1.pagination import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    paginate_sequence,
)
from backend.service.api.rest.v1.routes.workflow_runtime_support.responses import (
    build_workflow_app_runtime_contract as _build_workflow_app_runtime_contract,
    build_workflow_app_runtime_event_contract as _build_workflow_app_runtime_event_contract,
    build_workflow_app_runtime_instance_contract as _build_workflow_app_runtime_instance_contract,
    build_workflow_runtime_revision_contract as _build_workflow_runtime_revision_contract,
)
from backend.service.api.rest.v1.routes.workflow_runtime_support.schemas import (
    WorkflowAppRuntimeCreateRequestBody,
    WorkflowAppRuntimeSelectVersionRequestBody,
)
from backend.service.api.rest.v1.routes.workflow_runtime_support.services import (
    build_workflow_json_service_from_request as _build_workflow_json_service_from_request,
    build_workflow_runtime_service as _build_workflow_runtime_service,
    ensure_project_visible as _ensure_project_visible,
)
from backend.service.application.workflows.runtime.app_runtimes import (
    WorkflowAppRuntimeCreateRequest,
    WorkflowAppRuntimeSelectVersionRequest,
)


workflow_app_runtimes_router = APIRouter()


@workflow_app_runtimes_router.get("/app-runtimes/{workflow_runtime_id}/preview-snapshot")
def get_runtime_preview_snapshot(
    workflow_runtime_id: str, request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
) -> dict[str, object]:
    """返回 Runtime 发布快照，不读取或修改编辑草稿。"""
    service = _build_workflow_runtime_service(request)
    service.get_visible_workflow_app_runtime(workflow_runtime_id, visible_project_ids=principal.project_ids)
    return service.get_runtime_preview_snapshot(workflow_runtime_id)


@workflow_app_runtimes_router.post(
    "/app-runtimes",
    response_model=WorkflowAppRuntimeContract,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_app_runtime(
    body: WorkflowAppRuntimeCreateRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowAppRuntimeContract:
    """创建一条 WorkflowAppRuntime 记录。"""

    _ensure_project_visible(principal=principal, project_id=body.project_id)
    workflow_app_runtime = _build_workflow_runtime_service(
        request
    ).create_workflow_app_runtime(
        WorkflowAppRuntimeCreateRequest(
            project_id=body.project_id,
            application_id=body.application_id,
            workflow_app_version_id=body.workflow_app_version_id,
            execution_policy_id=body.execution_policy_id,
            display_name=body.display_name,
            request_timeout_seconds=body.request_timeout_seconds,
            heartbeat_interval_seconds=body.heartbeat_interval_seconds,
            heartbeat_timeout_seconds=body.heartbeat_timeout_seconds,
            metadata=dict(body.metadata),
        ),
        created_by=principal.principal_id,
    )
    return _build_workflow_app_runtime_contract(
        workflow_app_runtime,
        workflow_service=_build_workflow_json_service_from_request(request),
    )


@workflow_app_runtimes_router.get(
    "/app-runtimes/{workflow_runtime_id}/revisions",
    response_model=list[WorkflowRuntimeRevisionContract],
)
def list_workflow_runtime_revisions(
    workflow_runtime_id: str,
    request: Request,
    response: Response,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = DEFAULT_LIST_LIMIT,
) -> list[WorkflowRuntimeRevisionContract]:
    """分页列出稳定 Runtime 的版本选择历史。"""

    runtime_service = _build_workflow_runtime_service(request)
    runtime_service.get_visible_workflow_app_runtime(
        workflow_runtime_id,
        visible_project_ids=principal.project_ids,
    )
    revisions = runtime_service.list_workflow_runtime_revisions(workflow_runtime_id)
    page_items = paginate_sequence(
        revisions,
        response=response,
        offset=offset,
        limit=limit,
    )
    return [_build_workflow_runtime_revision_contract(item) for item in page_items]


@workflow_app_runtimes_router.get(
    "/app-runtimes/{workflow_runtime_id}/revisions/{workflow_runtime_revision_id}",
    response_model=WorkflowRuntimeRevisionContract,
)
def get_workflow_runtime_revision(
    workflow_runtime_id: str,
    workflow_runtime_revision_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
) -> WorkflowRuntimeRevisionContract:
    """读取稳定 Runtime 的一条不可变版本选择记录。"""

    runtime_service = _build_workflow_runtime_service(request)
    revision = runtime_service.get_visible_workflow_runtime_revision(
        workflow_runtime_id,
        workflow_runtime_revision_id,
        visible_project_ids=principal.project_ids,
    )
    return _build_workflow_runtime_revision_contract(revision)


@workflow_app_runtimes_router.post(
    "/app-runtimes/{workflow_runtime_id}/select-version",
    response_model=WorkflowAppRuntimeContract,
)
def select_workflow_app_runtime_version(
    workflow_runtime_id: str,
    body: WorkflowAppRuntimeSelectVersionRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowAppRuntimeContract:
    """在停机状态下为稳定 Runtime 选择已发布版本。"""

    runtime_service = _build_workflow_runtime_service(request)
    runtime_service.get_visible_workflow_app_runtime(
        workflow_runtime_id,
        visible_project_ids=principal.project_ids,
    )
    selected_runtime = runtime_service.select_workflow_app_runtime_version(
        workflow_runtime_id,
        WorkflowAppRuntimeSelectVersionRequest(
            workflow_app_version_id=body.workflow_app_version_id,
            expected_generation=body.expected_generation,
            allow_breaking_contract=body.allow_breaking_contract,
            breaking_change_reason=body.breaking_change_reason,
        ),
        updated_by=principal.principal_id,
    )
    return _build_workflow_app_runtime_contract(
        selected_runtime,
        workflow_service=_build_workflow_json_service_from_request(request),
    )


@workflow_app_runtimes_router.get(
    "/app-runtimes",
    response_model=list[WorkflowAppRuntimeContract],
)
def list_workflow_app_runtimes(
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
    application_id: Annotated[
        str | None,
        Query(description="可选 Workflow Application id 精确过滤"),
    ] = None,
    application_ids: Annotated[
        str | None,
        Query(description="可选逗号分隔 Workflow Application id 集合"),
    ] = None,
) -> list[WorkflowAppRuntimeContract]:
    """按 Project id 和可选 Application 过滤条件列出 Runtime。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    runtimes = _build_workflow_runtime_service(request).list_workflow_app_runtimes(
        project_id=project_id,
        application_id=application_id,
        application_ids=(
            tuple(application_ids.split(",")) if application_ids is not None else None
        ),
    )
    workflow_service = _build_workflow_json_service_from_request(request)
    paged_items = paginate_sequence(
        runtimes, response=response, offset=offset, limit=limit
    )
    return [
        _build_workflow_app_runtime_contract(item, workflow_service=workflow_service)
        for item in paged_items
    ]


@workflow_app_runtimes_router.get(
    "/app-runtimes/{workflow_runtime_id}",
    response_model=WorkflowAppRuntimeContract,
)
def get_workflow_app_runtime(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
) -> WorkflowAppRuntimeContract:
    """读取一条 WorkflowAppRuntime。"""

    workflow_app_runtime = _build_workflow_runtime_service(
        request
    ).get_visible_workflow_app_runtime(
        workflow_runtime_id,
        visible_project_ids=principal.project_ids,
    )
    return _build_workflow_app_runtime_contract(
        workflow_app_runtime,
        workflow_service=_build_workflow_json_service_from_request(request),
    )


@workflow_app_runtimes_router.get(
    "/app-runtimes/{workflow_runtime_id}/events",
    response_model=list[WorkflowAppRuntimeEventContract],
)
def get_workflow_app_runtime_events(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
    after_sequence: Annotated[
        int | None, Query(description="只返回 sequence 大于该值的事件", ge=0)
    ] = None,
    limit: Annotated[
        int | None, Query(description="最多返回多少条事件", ge=1, le=500)
    ] = None,
) -> list[WorkflowAppRuntimeEventContract]:
    """读取一条 WorkflowAppRuntime 的事件列表。"""

    runtime_service = _build_workflow_runtime_service(request)
    runtime_service.get_visible_workflow_app_runtime(
        workflow_runtime_id,
        visible_project_ids=principal.project_ids,
    )
    events = runtime_service.get_workflow_app_runtime_events(
        workflow_runtime_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return [_build_workflow_app_runtime_event_contract(item) for item in events]


@workflow_app_runtimes_router.post(
    "/app-runtimes/{workflow_runtime_id}/start",
    response_model=WorkflowAppRuntimeContract,
)
def start_workflow_app_runtime(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowAppRuntimeContract:
    """启动一个 WorkflowAppRuntime 对应的 worker。"""

    _build_workflow_runtime_service(request).get_visible_workflow_app_runtime(
        workflow_runtime_id,
        visible_project_ids=principal.project_ids,
    )
    updated_runtime = _build_workflow_runtime_service(
        request
    ).start_workflow_app_runtime(
        workflow_runtime_id,
        updated_by=principal.principal_id,
    )
    return _build_workflow_app_runtime_contract(
        updated_runtime,
        workflow_service=_build_workflow_json_service_from_request(request),
    )


@workflow_app_runtimes_router.post(
    "/app-runtimes/{workflow_runtime_id}/stop",
    response_model=WorkflowAppRuntimeContract,
)
def stop_workflow_app_runtime(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowAppRuntimeContract:
    """停止一个 WorkflowAppRuntime 对应的 worker。"""

    _build_workflow_runtime_service(request).get_visible_workflow_app_runtime(
        workflow_runtime_id,
        visible_project_ids=principal.project_ids,
    )
    updated_runtime = _build_workflow_runtime_service(
        request
    ).stop_workflow_app_runtime(
        workflow_runtime_id,
        updated_by=principal.principal_id,
    )
    return _build_workflow_app_runtime_contract(
        updated_runtime,
        workflow_service=_build_workflow_json_service_from_request(request),
    )


@workflow_app_runtimes_router.delete(
    "/app-runtimes/{workflow_runtime_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_workflow_app_runtime(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> Response:
    """删除一条 WorkflowAppRuntime 及其 snapshot 目录。"""

    runtime_service = _build_workflow_runtime_service(request)
    runtime_service.get_visible_workflow_app_runtime(
        workflow_runtime_id,
        visible_project_ids=principal.project_ids,
    )
    runtime_service.delete_workflow_app_runtime(
        workflow_runtime_id,
        deleted_by=principal.principal_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@workflow_app_runtimes_router.post(
    "/app-runtimes/{workflow_runtime_id}/restart",
    response_model=WorkflowAppRuntimeContract,
)
def restart_workflow_app_runtime(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowAppRuntimeContract:
    """重启一个 WorkflowAppRuntime 对应的 worker。"""

    _build_workflow_runtime_service(request).get_visible_workflow_app_runtime(
        workflow_runtime_id,
        visible_project_ids=principal.project_ids,
    )
    updated_runtime = _build_workflow_runtime_service(
        request
    ).restart_workflow_app_runtime(
        workflow_runtime_id,
        updated_by=principal.principal_id,
    )
    return _build_workflow_app_runtime_contract(
        updated_runtime,
        workflow_service=_build_workflow_json_service_from_request(request),
    )


@workflow_app_runtimes_router.get(
    "/app-runtimes/{workflow_runtime_id}/health",
    response_model=WorkflowAppRuntimeContract,
)
def get_workflow_app_runtime_health(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
) -> WorkflowAppRuntimeContract:
    """查询一个 WorkflowAppRuntime 的当前健康状态。"""

    _build_workflow_runtime_service(request).get_visible_workflow_app_runtime(
        workflow_runtime_id,
        visible_project_ids=principal.project_ids,
    )
    updated_runtime = _build_workflow_runtime_service(
        request
    ).get_workflow_app_runtime_health(workflow_runtime_id)
    return _build_workflow_app_runtime_contract(
        updated_runtime,
        workflow_service=_build_workflow_json_service_from_request(request),
    )


@workflow_app_runtimes_router.get(
    "/app-runtimes/{workflow_runtime_id}/instances",
    response_model=list[WorkflowAppRuntimeInstanceContract],
)
def list_workflow_app_runtime_instances(
    workflow_runtime_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
) -> list[WorkflowAppRuntimeInstanceContract]:
    """列出一个 WorkflowAppRuntime 当前可观测的 instance。"""

    _build_workflow_runtime_service(request).get_visible_workflow_app_runtime(
        workflow_runtime_id,
        visible_project_ids=principal.project_ids,
    )
    instances = _build_workflow_runtime_service(
        request
    ).list_workflow_app_runtime_instances(workflow_runtime_id)
    return [_build_workflow_app_runtime_instance_contract(item) for item in instances]
