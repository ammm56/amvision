"""workflow runtime preview run 路由。"""

from __future__ import annotations

import mimetypes
import logging
import sys
from functools import partial
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse
from starlette.datastructures import FormData, UploadFile

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
    create_local_buffer_broker_client as _create_local_buffer_broker_client,
    with_created_by as _with_created_by,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
    WorkflowInputError,
)
from backend.service.application.local_buffers import LocalBufferBrokerClient
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY,
    WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_TREE,
)
from backend.service.application.workflows.input_contracts import (
    DEFAULT_FILE_MAX_BYTES,
    WorkflowInputValidator,
)
from backend.service.application.workflows.preview_display_outputs import is_preview_run_artifact_object_key
from backend.service.application.workflows.runtime.preview_runs import WorkflowPreviewRunCreateRequest
from backend.service.api.rest.v1.routes.workflow_runtime_support.uploads import (
    WORKFLOW_RUNTIME_MULTIPART_CONTROL_PART_MAX_BYTES,
    contract_input_index,
    publish_workflow_upload,
    raise_file_count,
    read_contract_limit,
    validate_upload_media_type,
)


workflow_runtime_preview_runs_router = APIRouter()
LOGGER = logging.getLogger(__name__)

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
    """按公开 binding 处理图片、单文件和多文件 Preview 上传。"""

    form = await request.form(
        max_part_size=WORKFLOW_RUNTIME_MULTIPART_CONTROL_PART_MAX_BYTES
    )
    dataset_storage: LocalDatasetStorage | None = None
    preview_upload_id = uuid4().hex
    upload_root = ""
    lease_ids: list[str] = []
    client: LocalBufferBrokerClient | None = None
    published_any = False
    try:
        dataset_storage = _require_dataset_storage(request)
        raw_request_body = form.get("request")
        if not isinstance(raw_request_body, str) or not raw_request_body.strip():
            raise InvalidRequestError("multipart Preview 缺少 request JSON")
        try:
            body = WorkflowPreviewRunCreateRequestBody.model_validate_json(
                raw_request_body
            )
        except ValueError as exc:
            raise InvalidRequestError(
                "multipart Preview request 不是合法 JSON",
                details={"error_message": str(exc)},
            ) from exc
        upload_root = (
            f"workflows/runtime-inputs/{body.project_id}/preview/"
            f"{preview_upload_id}"
        )

        runtime_service = _build_workflow_runtime_service(request)
        preview_request = _build_preview_run_create_request(
            body=body,
            input_bindings=dict(body.input_bindings),
            execution_metadata=dict(body.execution_metadata),
        )
        application, public_contract = runtime_service.resolve_preview_input_contract(
            preview_request
        )
        contract_items = contract_input_index(public_contract)
        input_bindings = dict(body.input_bindings)

        upload_groups: dict[str, list[UploadFile]] = {}
        reserved_fields = {"request", "image_binding_id", "image_file"}
        for field_name, field_value in form.multi_items():
            if field_name in reserved_fields:
                continue
            if not isinstance(field_value, UploadFile):
                raise WorkflowInputError(
                    "multipart Preview 非文件字段必须放入 request.input_bindings",
                    code="workflow_input_payload_schema_invalid",
                    details={"field_name": field_name},
                )
            upload_groups.setdefault(field_name, []).append(field_value)

        legacy_binding_ids = [
            str(value).strip() for value in form.getlist("image_binding_id")
        ]
        legacy_image_files = form.getlist("image_file")
        if bool(legacy_binding_ids) != bool(legacy_image_files) or len(
            legacy_binding_ids
        ) != len(legacy_image_files):
            raise InvalidRequestError(
                "image_binding_id 与 image_file 必须一一对应"
            )
        if any(not binding_id for binding_id in legacy_binding_ids) or len(
            set(legacy_binding_ids)
        ) != len(legacy_binding_ids):
            raise InvalidRequestError("image_binding_id 不能为空或重复")
        if not upload_groups and not legacy_binding_ids:
            raise InvalidRequestError("multipart Preview 至少需要一个上传文件")

        requested_binding_ids = [*upload_groups, *legacy_binding_ids]
        for binding_id in requested_binding_ids:
            if binding_id in input_bindings:
                raise WorkflowInputError(
                    "multipart Preview 文件字段与 request.input_bindings 冲突",
                    code="workflow_input_multipart_binding_conflict",
                    details={"binding_id": binding_id},
                )
            if binding_id not in contract_items:
                raise WorkflowInputError(
                    "multipart Preview 上传字段未声明为 Workflow 输入 binding",
                    code="workflow_input_unknown_binding",
                    details={"binding_ids": [binding_id]},
                )
        if len(set(requested_binding_ids)) != len(requested_binding_ids):
            duplicated = sorted(
                binding_id
                for binding_id in set(requested_binding_ids)
                if requested_binding_ids.count(binding_id) > 1
            )
            raise WorkflowInputError(
                "multipart Preview 同一 binding 不能同时使用两种上传字段",
                code="workflow_input_multipart_binding_conflict",
                details={"binding_ids": duplicated},
            )

        image_uploads: list[tuple[str, UploadFile, dict[str, object]]] = []
        for binding_id, raw_upload in zip(
            legacy_binding_ids, legacy_image_files, strict=True
        ):
            if not isinstance(raw_upload, UploadFile):
                raise InvalidRequestError("image_file 不是有效的上传文件")
            contract_item = contract_items[binding_id]
            if contract_item.get("payload_type_id") != "image-ref.v1":
                raise WorkflowInputError(
                    "旧图片 Preview 字段只能映射到 image-ref.v1 binding",
                    code="workflow_input_payload_schema_invalid",
                    details={"binding_id": binding_id},
                )
            image_uploads.append((binding_id, raw_upload, contract_item))

        for binding_id, uploads in upload_groups.items():
            contract_item = contract_items[binding_id]
            payload_type_id = str(contract_item.get("payload_type_id") or "")
            maximum = (
                read_contract_limit(contract_item.get("max_files"), 64)
                if payload_type_id == "file-refs.v1"
                else 1
            )
            if len(uploads) > maximum:
                raise_file_count(
                    binding_id=binding_id,
                    count=len(uploads),
                    maximum=maximum,
                )
            if payload_type_id == "image-ref.v1":
                image_uploads.append((binding_id, uploads[0], contract_item))
                continue
            if payload_type_id not in {"file-ref.v1", "file-refs.v1"}:
                raise WorkflowInputError(
                    "当前 payload type 不支持 Preview multipart 文件 transport",
                    code="workflow_input_payload_schema_invalid",
                    details={
                        "binding_id": binding_id,
                        "payload_type_id": payload_type_id,
                    },
                )
            file_payloads: list[dict[str, object]] = []
            for item_index, upload in enumerate(uploads):
                file_payloads.append(
                    await publish_workflow_upload(
                        dataset_storage=dataset_storage,
                        upload=upload,
                        binding_id=binding_id,
                        item_index=item_index,
                        payload_type_id=payload_type_id,
                        contract_item=contract_item,
                        upload_root=upload_root,
                    )
                )
                published_any = True
            input_bindings[binding_id] = (
                {"items": file_payloads, "count": len(file_payloads)}
                if payload_type_id == "file-refs.v1"
                else file_payloads[0]
            )

        if image_uploads:
            client = _create_local_buffer_broker_client(request)
            if client is None:
                raise ServiceConfigurationError(
                    "LocalBufferBroker 未启用，无法执行图片 Preview"
                )
            owner_id = f"preview-upload-{preview_upload_id}"
            for binding_id, image_file, contract_item in image_uploads:
                input_bindings[binding_id] = await _write_preview_image_upload(
                    request=request,
                    client=client,
                    owner_id=owner_id,
                    body=body,
                    binding_id=binding_id,
                    image_file=image_file,
                    contract_item=contract_item,
                    lease_ids=lease_ids,
                )

        WorkflowInputValidator(object_store=dataset_storage).validate(
            application=application,
            input_bindings=input_bindings,
            public_contract=public_contract,
            project_id=body.project_id,
        )
        execution_metadata = dict(body.execution_metadata)
        if published_any:
            execution_metadata[WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY] = [
                {
                    "resource_kind": (
                        WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_TREE
                    ),
                    "resource_id": upload_root,
                    "metadata": {},
                }
            ]
        preview_run = _create_preview_run(
            body=body,
            request=request,
            principal=principal,
            input_bindings=input_bindings,
            execution_metadata=execution_metadata,
        )
        return _build_preview_run_contract(preview_run)
    finally:
        await _cleanup_preview_uploads(
            dataset_storage=dataset_storage,
            upload_root=upload_root,
            lease_ids=lease_ids,
            client=client,
            form=form,
            execution_failed=sys.exception() is not None,
        )


async def _cleanup_preview_uploads(
    *,
    dataset_storage: LocalDatasetStorage | None,
    upload_root: str,
    lease_ids: list[str],
    client: LocalBufferBrokerClient | None,
    form: FormData,
    execution_failed: bool,
) -> None:
    """逐项释放本次上传资源；清理失败不跳过后续释放或覆盖原始执行异常。"""

    cleanup_actions = []
    if dataset_storage is not None and upload_root:
        cleanup_actions.append(partial(_delete_preview_upload_root, dataset_storage, upload_root))
    if client is not None:
        cleanup_actions.extend(partial(client.release, lease_id) for lease_id in lease_ids)
        cleanup_actions.append(client.close)
    first_error: Exception | None = None
    for cleanup in cleanup_actions:
        try:
            cleanup()
        except Exception as exc:
            first_error = first_error or exc
            LOGGER.exception("Preview 上传资源清理失败")
    # FormData.close 在首个文件关闭异常时会中断，逐项关闭确保其余文件仍被释放。
    for _name, upload in form.multi_items():
        if not isinstance(upload, UploadFile):
            continue
        try:
            await upload.close()
        except Exception as exc:
            first_error = first_error or exc
            LOGGER.exception("Preview 上传文件关闭失败")
    if first_error is not None and not execution_failed:
        raise first_error


def _delete_preview_upload_root(dataset_storage: LocalDatasetStorage, upload_root: str) -> None:
    """删除本次请求的上传目录，并检查底层忽略删除错误后是否仍有残留。"""

    dataset_storage.delete_tree(upload_root)
    try:
        dataset_storage.resolve_filesystem_path(upload_root).stat()
    except FileNotFoundError:
        return
    raise OSError(f"Preview 上传目录未完全删除: {upload_root}")


async def _write_preview_image_upload(
    *,
    request: Request,
    client: LocalBufferBrokerClient,
    owner_id: str,
    body: WorkflowPreviewRunCreateRequestBody,
    binding_id: str,
    image_file: UploadFile,
    contract_item: dict[str, object],
    lease_ids: list[str],
) -> dict[str, object]:
    """按契约上限读取一张 Preview 图片并写入 LocalBuffer。"""

    media_type = (
        image_file.content_type.strip().lower()
        if isinstance(image_file.content_type, str)
        and image_file.content_type.strip()
        else (
            mimetypes.guess_type(image_file.filename or "")[0]
            or "application/octet-stream"
        )
    )
    validate_upload_media_type(
        binding_id=binding_id,
        media_type=media_type,
        contract_item=contract_item,
    )
    max_file_bytes = read_contract_limit(
        contract_item.get("max_file_bytes"), DEFAULT_FILE_MAX_BYTES
    )
    content = await image_file.read(max_file_bytes + 1)
    if len(content) > max_file_bytes:
        raise WorkflowInputError(
            "Preview 图片超过公开输入契约限制",
            code="workflow_input_file_size_exceeded",
            details={
                "binding_id": binding_id,
                "max_file_bytes": max_file_bytes,
            },
        )
    if not content:
        raise WorkflowInputError(
            "Preview 图片不能为空",
            code="workflow_input_payload_schema_invalid",
            details={"binding_id": binding_id},
        )
    write_result = client.write_bytes(
        content=content,
        owner_kind="workflow-preview-upload",
        owner_id=owner_id,
        media_type=media_type,
        ttl_seconds=float(body.timeout_seconds or 120) + 30.0,
        trace_id=getattr(request.state, "request_id", None),
    )
    lease_ids.append(write_result.lease.lease_id)
    return {
        "transport_kind": "buffer",
        "media_type": media_type,
        "buffer_ref": write_result.buffer_ref.model_dump(mode="json"),
    }


def _create_preview_run(
    *,
    body: WorkflowPreviewRunCreateRequestBody,
    request: Request,
    principal: AuthenticatedPrincipal,
    input_bindings: dict[str, object],
    execution_metadata: dict[str, object] | None = None,
):
    """按统一参数创建 JSON 或 LocalBuffer multipart Preview。"""

    _ensure_project_visible(principal=principal, project_id=body.project_id)
    execution_metadata = _with_created_by(
        execution_metadata
        if execution_metadata is not None
        else body.execution_metadata,
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
    return _build_workflow_runtime_service(request).create_preview_run(
        _build_preview_run_create_request(
            body=body,
            input_bindings=input_bindings,
            execution_metadata=execution_metadata,
        ),
        created_by=principal.principal_id,
    )


def _build_preview_run_create_request(
    *,
    body: WorkflowPreviewRunCreateRequestBody,
    input_bindings: dict[str, object],
    execution_metadata: dict[str, object],
) -> WorkflowPreviewRunCreateRequest:
    """把 REST body 转换为唯一的应用层 Preview 请求。"""

    return WorkflowPreviewRunCreateRequest(
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

    preview_run = _build_workflow_runtime_service(request).get_visible_preview_run(
        preview_run_id,
        visible_project_ids=principal.project_ids,
    )
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

    preview_run = _build_workflow_runtime_service(request).get_visible_preview_run(
        preview_run_id,
        visible_project_ids=principal.project_ids,
    )
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
    runtime_service.get_visible_preview_run(
        preview_run_id,
        visible_project_ids=principal.project_ids,
    )
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

    _build_workflow_runtime_service(request).get_visible_preview_run(
        preview_run_id,
        visible_project_ids=principal.project_ids,
    )
    _build_workflow_runtime_service(request).delete_preview_run(preview_run_id)
