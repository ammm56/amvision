"""同步推理显式保存记录 REST 路由。"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.pagination import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    paginate_sequence,
)
from backend.service.api.rest.v1.routes.inference_records.schemas import (
    DirectInferenceRecordDetailResponse,
    DirectInferenceRecordSaveRequestBody,
    DirectInferenceRecordSummaryResponse,
    build_direct_inference_record_summary_response,
)
from backend.service.api.rest.v1.routes.projects.responses import guess_media_type
from backend.service.api.rest.v1.routes.tasks.visibility import resolve_visible_project_ids
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError
from backend.service.application.models.inference.direct_inference_record_service import (
    SaveDirectInferenceRecordCommand,
    SqlAlchemyDirectInferenceRecordService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)

inference_records_router = APIRouter(prefix="/inference-records", tags=["inference"])


def _build_record_service(
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> SqlAlchemyDirectInferenceRecordService:
    """装配同步推理保存记录应用服务。"""

    return SqlAlchemyDirectInferenceRecordService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


@inference_records_router.post(
    "",
    response_model=DirectInferenceRecordSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_direct_inference_record(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DirectInferenceRecordSummaryResponse:
    """显式保存一次同步推理结果（支持手动保存、失败仅重试保存及 request_id 幂等去重）。"""

    content_type = (request.headers.get("content-type") or "").lower()
    input_image_bytes: bytes | None = None
    input_image_filename: str | None = None
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        try:
            payload_raw = form.get("payload")
            if not isinstance(payload_raw, str) or not payload_raw.strip():
                raise InvalidRequestError("multipart 请求缺少 payload JSON 字段")
            try:
                raw_json = json.loads(payload_raw)
            except json.JSONDecodeError as error:
                raise InvalidRequestError("payload 不是合法的 JSON") from error
            upload = form.get("input_image")
            if upload is not None:
                if not hasattr(upload, "read"):
                    raise InvalidRequestError("input_image 必须是有效的上传文件")
                input_image_bytes = await upload.read()
                input_image_filename = getattr(upload, "filename", None)
        finally:
            await form.close()
    else:
        try:
            raw_json = await request.json()
        except Exception as error:
            raise InvalidRequestError("请求体不是合法的 JSON") from error

    try:
        body = DirectInferenceRecordSaveRequestBody.model_validate(raw_json)
    except Exception as error:
        raise InvalidRequestError(
            "保存同步推理记录请求格式不合法",
            details={"error": str(error)},
        ) from error

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权写入该 Project 的推理记录",
            details={"project_id": body.project_id},
        )

    service = _build_record_service(session_factory, dataset_storage)
    record = service.save_record(
        SaveDirectInferenceRecordCommand(
            project_id=body.project_id,
            request_id=body.request_id,
            task_type=body.task_type,
            deployment_instance_id=body.deployment_instance_id,
            result_payload=dict(body.result_payload),
            input_label=body.input_label,
            input_image_bytes=input_image_bytes,
            input_image_filename=input_image_filename,
            input_image_base64=body.input_image_base64,
            parameters=dict(body.parameters),
            created_by=principal.principal_id,
        )
    )
    return build_direct_inference_record_summary_response(record)


@inference_records_router.get(
    "",
    response_model=list[DirectInferenceRecordSummaryResponse],
)
def list_direct_inference_records(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    response: Response,
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    task_type: Annotated[str | None, Query(description="任务类型过滤")] = None,
    deployment_instance_id: Annotated[str | None, Query(description="部署实例 id 过滤")] = None,
    request_id: Annotated[str | None, Query(description="按同步 request_id 精确反查")] = None,
    q: Annotated[str | None, Query(description="关键词检索")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = DEFAULT_LIST_LIMIT,
) -> list[DirectInferenceRecordSummaryResponse]:
    """分页列出显式保存的同步推理记录，同时支持超时后按 request_id 反查。"""

    visible_projects = resolve_visible_project_ids(
        principal=principal,
        project_id=project_id,
    )
    service = _build_record_service(session_factory, dataset_storage)
    all_records = []
    for current_project_id in visible_projects:
        all_records.extend(
            service.list_records(
                project_id=current_project_id,
                task_type=task_type,
                deployment_instance_id=deployment_instance_id,
                request_id=request_id,
                q=q,
            )
        )
    all_records.sort(key=lambda item: (item.created_at, item.record_id), reverse=True)
    paged = paginate_sequence(all_records, response=response, offset=offset, limit=limit)
    return [build_direct_inference_record_summary_response(item) for item in paged]


@inference_records_router.get(
    "/{record_id}",
    response_model=DirectInferenceRecordDetailResponse,
)
def get_direct_inference_record_detail(
    record_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DirectInferenceRecordDetailResponse:
    """读取单条同步保存记录详情及完整结果 JSON。"""

    service = _build_record_service(session_factory, dataset_storage)
    record = service.get_record(record_id, visible_project_ids=principal.project_ids)
    file_status, result_payload = service.read_record_payload(record)
    summary = build_direct_inference_record_summary_response(record)
    return DirectInferenceRecordDetailResponse(
        **summary.model_dump(),
        file_status=file_status,  # type: ignore[arg-type]
        result_payload=result_payload,
    )


@inference_records_router.get("/{record_id}/image")
def get_direct_inference_record_image(
    record_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    kind: Annotated[Literal["input", "preview"], Query(description="图片类型")] = "input",
    download: Annotated[bool, Query(description="是否按附件下载")] = False,
) -> FileResponse:
    """读取或下载同步保存记录关联的输入原图或服务端渲染预览图。"""

    service = _build_record_service(session_factory, dataset_storage)
    record = service.get_record(record_id, visible_project_ids=principal.project_ids)
    object_key, file_path = service.resolve_record_image_path(record, kind=kind)
    media_type = guess_media_type(file_path, object_key=object_key)
    filename = file_path.name if download else None
    return FileResponse(path=file_path, media_type=media_type, filename=filename)


@inference_records_router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_direct_inference_record(
    record_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> Response:
    """删除同步推理保存记录并同步清理产物目录；清理失败时保留记录以允许重试。"""

    service = _build_record_service(session_factory, dataset_storage)
    service.delete_record(record_id, visible_project_ids=principal.project_ids)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
