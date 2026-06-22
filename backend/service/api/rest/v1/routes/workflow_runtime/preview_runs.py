"""workflow runtime preview run 路由。"""

from __future__ import annotations

import mimetypes
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse

from backend.contracts.workflows import (
    WorkflowPreviewRunContract,
    WorkflowPreviewRunEventContract,
    WorkflowPreviewRunSummaryContract,
)
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.rest.v1.pagination import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, paginate_sequence
from backend.service.api.rest.v1.routes.workflow_runtime_support.responses import (
    build_preview_run_contract as _build_preview_run_contract,
    build_preview_run_event_contract as _build_preview_run_event_contract,
    build_preview_run_summary_contract as _build_preview_run_summary_contract,
)
from backend.service.api.rest.v1.routes.workflow_runtime_support.schemas import WorkflowPreviewRunCreateRequestBody
from backend.service.api.rest.v1.routes.workflow_runtime_support.services import (
    build_workflow_runtime_service as _build_workflow_runtime_service,
    ensure_project_visible as _ensure_project_visible,
    require_dataset_storage as _require_dataset_storage,
    with_created_by as _with_created_by,
)
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.workflows.preview_display_outputs import is_preview_run_artifact_object_key
from backend.service.application.workflows.runtime.preview_runs import WorkflowPreviewRunCreateRequest


workflow_runtime_preview_runs_router = APIRouter()

@workflow_runtime_preview_runs_router.post(
    "/preview-runs",
    response_model=WorkflowPreviewRunContract,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_preview_run(
    body: WorkflowPreviewRunCreateRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowPreviewRunContract:
    """创建一条 preview run，支持 sync/async wait_mode。"""

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
            wait_mode=body.wait_mode,
        ),
        created_by=principal.principal_id,
    )
    return _build_preview_run_contract(preview_run)


@workflow_runtime_preview_runs_router.get(
    "/preview-runs",
    response_model=list[WorkflowPreviewRunSummaryContract],
)
def list_workflow_preview_runs(
    project_id: Annotated[str, Query(description="所属 Project id")],
    request: Request,
    response: Response,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    state: Annotated[str | None, Query(description="按 preview run 状态过滤")] = None,
    created_from: Annotated[str | None, Query(description="按 created_at 下界过滤，ISO8601")]= None,
    created_to: Annotated[str | None, Query(description="按 created_at 上界过滤，ISO8601")] = None,
    offset: Annotated[int, Query(ge=0, description="结果偏移量")] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT, description="最大返回数量")] = DEFAULT_LIST_LIMIT,
) -> list[WorkflowPreviewRunSummaryContract]:
    """按 Project id、状态和创建时间范围列出 WorkflowPreviewRun 摘要。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    preview_runs = _build_workflow_runtime_service(request).list_preview_runs_filtered(
        project_id=project_id,
        state=state,
        created_from=created_from,
        created_to=created_to,
    )
    paged_items = paginate_sequence(preview_runs, response=response, offset=offset, limit=limit)
    return [_build_preview_run_summary_contract(item) for item in paged_items]


@workflow_runtime_preview_runs_router.get(
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


@workflow_runtime_preview_runs_router.get("/preview-runs/{preview_run_id}/artifacts/content")
def read_workflow_preview_run_artifact_content(
    preview_run_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    object_key: Annotated[str, Query(description="Preview Run artifact object key")],
    download: Annotated[bool, Query(description="是否按附件下载")] = False,
) -> FileResponse:
    """读取一个 Preview Run 生命周期内的 artifact 文件内容。"""

    preview_run = _build_workflow_runtime_service(request).get_preview_run(preview_run_id)
    _ensure_project_visible(principal=principal, project_id=preview_run.project_id)
    normalized_object_key = object_key.strip()
    if not is_preview_run_artifact_object_key(
        preview_run_id=preview_run.preview_run_id,
        object_key=normalized_object_key,
    ):
        raise InvalidRequestError(
            "当前接口只允许读取指定 Preview Run 的 artifact 文件",
            details={"preview_run_id": preview_run.preview_run_id, "object_key": normalized_object_key},
        )
    file_path = _require_dataset_storage(request).resolve(normalized_object_key)
    if not file_path.is_file():
        raise ResourceNotFoundError(
            "请求的 Preview Run artifact 文件不存在",
            details={"preview_run_id": preview_run.preview_run_id, "object_key": normalized_object_key},
        )
    media_type, _ = mimetypes.guess_type(normalized_object_key)
    return FileResponse(
        path=file_path,
        media_type=media_type or "application/octet-stream",
        filename=file_path.name if download else None,
    )


@workflow_runtime_preview_runs_router.get(
    "/preview-runs/{preview_run_id}/events",
    response_model=list[WorkflowPreviewRunEventContract],
)
def get_workflow_preview_run_events(
    preview_run_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    after_sequence: Annotated[int | None, Query(description="只返回 sequence 大于该值的事件", ge=0)] = None,
    limit: Annotated[int | None, Query(description="最多返回多少条事件", ge=1, le=500)] = None,
) -> list[WorkflowPreviewRunEventContract]:
    """读取一条 preview run 的执行事件。"""

    runtime_service = _build_workflow_runtime_service(request)
    preview_run = runtime_service.get_preview_run(preview_run_id)
    _ensure_project_visible(principal=principal, project_id=preview_run.project_id)
    events = runtime_service.get_preview_run_events(
        preview_run_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return [_build_preview_run_event_contract(item) for item in events]


@workflow_runtime_preview_runs_router.post(
    "/preview-runs/{preview_run_id}/cancel",
    response_model=WorkflowPreviewRunContract,
)
def cancel_workflow_preview_run(
    preview_run_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowPreviewRunContract:
    """取消一条 preview run。"""

    runtime_service = _build_workflow_runtime_service(request)
    preview_run = runtime_service.get_preview_run(preview_run_id)
    _ensure_project_visible(principal=principal, project_id=preview_run.project_id)
    updated_preview_run = runtime_service.cancel_preview_run(
        preview_run_id,
        cancelled_by=principal.principal_id,
    )
    return _build_preview_run_contract(updated_preview_run)


@workflow_runtime_preview_runs_router.delete(
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
