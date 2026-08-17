"""workflow runtime preview run 路由。"""

from __future__ import annotations

import mimetypes
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile

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
    read_local_buffer_broker_event_channel as _read_local_buffer_broker_event_channel,
    with_created_by as _with_created_by,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.local_buffers import LocalBufferBrokerClient
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
    """创建并同步执行一条 preview run。"""

    _ensure_project_visible(principal=principal, project_id=body.project_id)
    preview_run = _create_preview_run(
        body=body,
        request=request,
        principal=principal,
        input_bindings=dict(body.input_bindings),
    )
    return _build_preview_run_contract(preview_run)


@workflow_runtime_preview_runs_router.post(
    "/preview-runs/multipart",
    response_model=WorkflowPreviewRunContract,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow_preview_run_multipart(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
) -> WorkflowPreviewRunContract:
    """把 Preview 图片写入 LocalBuffer 后按 image-ref 执行同步 Preview。"""

    form = await request.form()
    raw_request_body = form.get("request")
    if not isinstance(raw_request_body, str) or not raw_request_body.strip():
        raise InvalidRequestError("multipart Preview 缺少 request JSON")
    try:
        body = WorkflowPreviewRunCreateRequestBody.model_validate_json(raw_request_body)
    except ValueError as exc:
        raise InvalidRequestError(
            "multipart Preview request 不是合法 JSON",
            details={"error_message": str(exc)},
        ) from exc
    if body.wait_mode != "sync":
        raise InvalidRequestError("LocalBuffer 图片 Preview 当前只支持 sync wait_mode")

    binding_ids = [str(value).strip() for value in form.getlist("image_binding_id")]
    image_files = form.getlist("image_file")
    if len(binding_ids) != len(image_files) or not binding_ids:
        raise InvalidRequestError("image_binding_id 与 image_file 必须一一对应")
    if any(not binding_id for binding_id in binding_ids) or len(set(binding_ids)) != len(binding_ids):
        raise InvalidRequestError("image_binding_id 不能为空或重复")

    channel = _read_local_buffer_broker_event_channel(request)
    if channel is None:
        raise ServiceConfigurationError("LocalBufferBroker 未启用，无法执行图片 Preview")
    input_bindings = dict(body.input_bindings)
    lease_refs: list[tuple[str, str]] = []
    client = LocalBufferBrokerClient(channel)
    try:
        owner_id = f"preview-upload-{uuid4().hex}"
        for binding_id, image_file in zip(binding_ids, image_files, strict=True):
            if not isinstance(image_file, UploadFile):
                raise InvalidRequestError("image_file 不是有效的上传文件")
            content = await image_file.read()
            if not content:
                raise InvalidRequestError(
                    "Preview 图片不能为空",
                    details={"binding_id": binding_id},
                )
            media_type = (
                image_file.content_type
                or mimetypes.guess_type(image_file.filename or "")[0]
                or "application/octet-stream"
            )
            write_result = client.write_bytes(
                content=content,
                owner_kind="workflow-preview-upload",
                owner_id=owner_id,
                media_type=media_type,
                ttl_seconds=float(body.timeout_seconds or 120) + 30.0,
                trace_id=getattr(request.state, "request_id", None),
            )
            lease_refs.append(
                (write_result.lease.lease_id, write_result.lease.pool_name)
            )
            input_bindings[binding_id] = {
                "transport_kind": "buffer",
                "buffer_ref": write_result.buffer_ref.model_dump(mode="json"),
            }
        preview_run = _create_preview_run(
            body=body,
            request=request,
            principal=principal,
            input_bindings=input_bindings,
        )
        return _build_preview_run_contract(preview_run)
    finally:
        for lease_id, pool_name in lease_refs:
            try:
                client.release(lease_id, pool_name=pool_name)
            except Exception:
                pass
        client.close()


def _create_preview_run(
    *,
    body: WorkflowPreviewRunCreateRequestBody,
    request: Request,
    principal: AuthenticatedPrincipal,
    input_bindings: dict[str, object],
):
    """按统一参数创建 JSON 或 LocalBuffer multipart Preview。"""

    _ensure_project_visible(principal=principal, project_id=body.project_id)
    execution_metadata = _with_created_by(
        body.execution_metadata,
        principal.principal_id,
    )
    timings = execution_metadata.get("timings")
    timing_payload = dict(timings) if isinstance(timings, dict) else {}
    request_started_at = getattr(request.state, "request_started_at", None)
    if isinstance(request_started_at, float):
        timing_payload["request_parse_ms"] = round(
            max(0.0, (perf_counter() - request_started_at) * 1000.0),
            3,
        )
    execution_metadata["timings"] = timing_payload
    return _build_workflow_runtime_service(
        request,
        include_local_buffer_broker_event_channel=True,
    ).create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id=body.project_id,
            application_ref_id=(
                body.application_ref.application_id
                if body.application_ref is not None
                else None
            ),
            execution_policy_id=body.execution_policy_id,
            application=body.application,
            template=body.template,
            input_bindings=input_bindings,
            execution_metadata=execution_metadata,
            timeout_seconds=body.timeout_seconds,
            wait_mode=body.wait_mode,
            execution_scope_kind=body.execution_scope.kind,
            target_node_id=body.execution_scope.target_node_id,
        ),
        created_by=principal.principal_id,
    )


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
