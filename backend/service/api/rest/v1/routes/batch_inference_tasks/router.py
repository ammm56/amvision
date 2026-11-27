"""批量推理任务 REST 路由（支持 async 与 sync 双通道部署）。"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.pagination import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    paginate_sequence,
)
from backend.service.api.rest.v1.routes.batch_inference_tasks.schemas import (
    BatchInferenceTaskCreateJsonBody,
    BatchInferenceTaskItemResponse,
    BatchInferenceTaskItemResultResponse,
    BatchInferenceTaskResponse,
    build_batch_inference_task_item_response,
    build_batch_inference_task_response,
)
from backend.service.api.rest.v1.routes.projects.responses import guess_media_type
from backend.service.api.rest.v1.routes.task_deployments.runtime_controls import (
    read_async_inference_service_id,
)
from backend.service.api.rest.v1.routes.tasks.visibility import resolve_visible_project_ids
from backend.service.application.errors import (
    InvalidRequestError,
    PermissionDeniedError,
    ServiceConfigurationError,
)
from backend.service.application.models.inference.batch_inference_task_service import (
    CreateBatchInferenceTaskCommand,
    SqlAlchemyBatchInferenceTaskService,
    UploadedBatchImageInput,
)
from backend.service.application.models.inference.direct_inference_record_service import (
    normalize_inference_task_type,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.infrastructure.queue.local_file import LocalFileQueueBackend

batch_inference_tasks_router = APIRouter(prefix="/inference-batches", tags=["inference"])

_ASYNC_SUPERVISOR_ATTRS: dict[str, str] = {
    "detection": "detection_async_deployment_process_supervisor",
    "classification": "classification_async_deployment_process_supervisor",
    "segmentation": "segmentation_async_deployment_process_supervisor",
    "pose": "pose_async_deployment_process_supervisor",
    "obb": "obb_async_deployment_process_supervisor",
}
_SYNC_SUPERVISOR_ATTRS: dict[str, str] = {
    "detection": "detection_sync_deployment_process_supervisor",
    "classification": "classification_sync_deployment_process_supervisor",
    "segmentation": "segmentation_sync_deployment_process_supervisor",
    "pose": "pose_sync_deployment_process_supervisor",
    "obb": "obb_sync_deployment_process_supervisor",
}
_ASYNC_REGISTRY_ATTRS: dict[str, str] = {
    "detection": "detection_async_inference_gateway_dispatcher_registry",
    "classification": "classification_async_inference_gateway_dispatcher_registry",
    "segmentation": "segmentation_async_inference_gateway_dispatcher_registry",
    "pose": "pose_async_inference_gateway_dispatcher_registry",
    "obb": "obb_async_inference_gateway_dispatcher_registry",
}


def _resolve_runtime_components(
    request: Request,
    task_type: str,
) -> tuple[
    DeploymentProcessSupervisor | None,
    DeploymentProcessSupervisor | None,
    object | None,
]:
    """按任务类型解析 sync/async 部署监督器与异步网关分发器。"""

    normalized = normalize_inference_task_type(task_type)
    sync_attr = _SYNC_SUPERVISOR_ATTRS[normalized]
    async_attr = _ASYNC_SUPERVISOR_ATTRS[normalized]
    raw_sync = getattr(request.app.state, sync_attr, None)
    raw_async = getattr(request.app.state, async_attr, None)
    sync_supervisor = raw_sync if isinstance(raw_sync, DeploymentProcessSupervisor) else None
    async_supervisor = raw_async if isinstance(raw_async, DeploymentProcessSupervisor) else None
    if sync_supervisor is None and async_supervisor is None:
        raise ServiceConfigurationError(
            f"当前服务尚未装配 {normalized} 同步或异步部署监督器",
            details={"state_fields": [sync_attr, async_attr]},
        )
    registry_attr = _ASYNC_REGISTRY_ATTRS[normalized]
    registry = getattr(request.app.state, registry_attr, None)
    return sync_supervisor, async_supervisor, registry


def _build_batch_service(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    queue_backend: LocalFileQueueBackend,
    sync_supervisor: DeploymentProcessSupervisor | None = None,
) -> SqlAlchemyBatchInferenceTaskService:
    """装配批量推理任务应用服务。"""

    return SqlAlchemyBatchInferenceTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        sync_supervisor=sync_supervisor,
    )


@batch_inference_tasks_router.post(
    "",
    response_model=BatchInferenceTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_batch_inference_task(
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("models:read", "tasks:write")),
    ],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> BatchInferenceTaskResponse:
    """创建批量异步推理任务（支持多图上传、数据集版本/划分、项目文件三种互斥来源）。"""

    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        try:
            project_id = str(form.get("project_id") or "").strip()
            task_type = str(form.get("task_type") or "").strip()
            deployment_instance_id = str(form.get("deployment_instance_id") or "").strip()
            display_name = str(form.get("display_name") or "").strip()
            runtime_mode = str(form.get("runtime_mode") or "auto").strip().lower()
            if runtime_mode not in {"auto", "async", "sync"}:
                raise InvalidRequestError(
                    "批量推理 runtime_mode 不合法",
                    details={"runtime_mode": runtime_mode, "supported": ["auto", "async", "sync"]},
                )
            score_threshold = float(form.get("score_threshold") or 0.3)
            top_k = int(form.get("top_k") or 5)
            mask_threshold = float(form.get("mask_threshold") or 0.5)
            keypoint_threshold = float(form.get("keypoint_confidence_threshold") or 0.3)
            save_result_image = str(form.get("save_result_image") or "true").lower() in {
                "1",
                "true",
                "yes",
            }
            extra_options_raw = form.get("extra_options")
            extra_options: dict[str, object] = {}
            if isinstance(extra_options_raw, str) and extra_options_raw.strip():
                extra_options = json.loads(extra_options_raw)
            uploads: list[UploadedBatchImageInput] = []
            for field_name in ("input_images", "input_image"):
                for entry in form.getlist(field_name):
                    if hasattr(entry, "read"):
                        content = await entry.read()
                        uploads.append(
                            UploadedBatchImageInput(
                                filename=str(getattr(entry, "filename", None) or "image.jpg"),
                                content=content,
                            )
                        )
            command = CreateBatchInferenceTaskCommand(
                project_id=project_id,
                task_type=task_type,
                deployment_instance_id=deployment_instance_id,
                display_name=display_name,
                source_kind="upload",
                runtime_mode=runtime_mode,
                uploaded_images=tuple(uploads),
                score_threshold=score_threshold,
                top_k=top_k,
                mask_threshold=mask_threshold,
                keypoint_confidence_threshold=keypoint_threshold,
                save_result_image=save_result_image,
                extra_options=extra_options,
                created_by=principal.principal_id,
                async_inference_owner_id=(
                    read_async_inference_service_id(
                        request,
                        task_type=normalize_inference_task_type(task_type),
                    )
                    or "backend-service"
                ),
            )
        finally:
            await form.close()
    else:
        try:
            raw_json = await request.json()
            body = BatchInferenceTaskCreateJsonBody.model_validate(raw_json)
        except Exception as error:
            raise InvalidRequestError(
                "创建批量推理任务请求不合法",
                details={"error": str(error)},
            ) from error
        command = CreateBatchInferenceTaskCommand(
            project_id=body.project_id,
            task_type=body.task_type,
            deployment_instance_id=body.deployment_instance_id,
            display_name=body.display_name,
            source_kind=body.source_kind,
            runtime_mode=body.runtime_mode,
            dataset_id=body.dataset_id,
            dataset_version_id=body.dataset_version_id,
            dataset_split=body.dataset_split,
            sample_ids=tuple(body.sample_ids),
            input_file_ids=tuple(body.input_file_ids),
            score_threshold=body.score_threshold,
            top_k=body.top_k,
            mask_threshold=body.mask_threshold,
            keypoint_confidence_threshold=body.keypoint_confidence_threshold,
            save_result_image=body.save_result_image,
            extra_options=dict(body.extra_options),
            created_by=principal.principal_id,
            async_inference_owner_id=(
                read_async_inference_service_id(
                    request,
                    task_type=normalize_inference_task_type(body.task_type),
                )
                or "backend-service"
            ),
        )

    if principal.project_ids and command.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": command.project_id},
        )

    sync_supervisor, async_supervisor, async_gateway_registry = _resolve_runtime_components(
        request,
        command.task_type,
    )
    service = _build_batch_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        sync_supervisor=sync_supervisor,
    )
    task = service.create_batch_task(
        command,
        sync_supervisor=sync_supervisor,
        async_supervisor=async_supervisor,
        async_gateway_registry=async_gateway_registry,
    )
    return build_batch_inference_task_response(task)


@batch_inference_tasks_router.get(
    "",
    response_model=list[BatchInferenceTaskResponse],
)
def list_batch_inference_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    response: Response,
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    task_type: Annotated[str | None, Query(description="任务类型过滤")] = None,
    state: Annotated[str | None, Query(description="状态过滤")] = None,
    deployment_instance_id: Annotated[str | None, Query(description="部署实例 id 过滤")] = None,
    q: Annotated[str | None, Query(description="关键词检索")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = DEFAULT_LIST_LIMIT,
) -> list[BatchInferenceTaskResponse]:
    """分页列出批量异步推理任务。"""

    visible_projects = resolve_visible_project_ids(
        principal=principal,
        project_id=project_id,
    )
    service = _build_batch_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    all_tasks = []
    for current_project_id in visible_projects:
        all_tasks.extend(
            service.list_batch_tasks(
                project_id=current_project_id,
                task_type=task_type,
                state=state,
                deployment_instance_id=deployment_instance_id,
                q=q,
            )
        )
    all_tasks.sort(key=lambda item: (item.created_at, item.batch_task_id), reverse=True)
    paged = paginate_sequence(all_tasks, response=response, offset=offset, limit=limit)
    return [build_batch_inference_task_response(item) for item in paged]


@batch_inference_tasks_router.get(
    "/{batch_task_id}",
    response_model=BatchInferenceTaskResponse,
)
def get_batch_inference_task_detail(
    batch_task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> BatchInferenceTaskResponse:
    """获取单条批量推理任务详情。"""

    service = _build_batch_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    task = service.get_batch_task(
        batch_task_id,
        visible_project_ids=principal.project_ids,
    )
    return build_batch_inference_task_response(task)


@batch_inference_tasks_router.get(
    "/{batch_task_id}/items",
    response_model=list[BatchInferenceTaskItemResponse],
)
def list_batch_inference_task_items(
    batch_task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    response: Response,
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    state: Annotated[str | None, Query(description="子项状态过滤")] = None,
    q: Annotated[str | None, Query(description="子项关键词检索")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = DEFAULT_LIST_LIMIT,
) -> list[BatchInferenceTaskItemResponse]:
    """分页读取批量推理任务下的逐张图像执行结果明细。"""

    service = _build_batch_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    items = service.list_batch_items(
        batch_task_id,
        visible_project_ids=principal.project_ids,
        state=state,
        q=q,
    )
    paged = paginate_sequence(items, response=response, offset=offset, limit=limit)
    return [build_batch_inference_task_item_response(item) for item in paged]


@batch_inference_tasks_router.get(
    "/{batch_task_id}/items/{item_id}/result",
    response_model=BatchInferenceTaskItemResultResponse,
)
def get_batch_inference_task_item_result(
    batch_task_id: str,
    item_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> BatchInferenceTaskItemResultResponse:
    """读取批量推理单张图像子项的完整 JSON 推理结果。"""

    service = _build_batch_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    item, file_status, payload = service.get_batch_item_result(
        batch_task_id,
        item_id,
        visible_project_ids=principal.project_ids,
    )
    return BatchInferenceTaskItemResultResponse(
        file_status=file_status,  # type: ignore[arg-type]
        item_state=item.state,
        object_key=item.result_object_key,
        payload=payload,
    )


@batch_inference_tasks_router.get("/{batch_task_id}/items/{item_id}/image")
def get_batch_inference_task_item_image(
    batch_task_id: str,
    item_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    kind: Annotated[Literal["input", "preview"], Query(description="图片类型")] = "input",
    download: Annotated[bool, Query(description="是否按附件下载")] = False,
) -> FileResponse:
    """读取或下载批量推理单张图像子项的原图或服务端预览图。"""

    service = _build_batch_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    object_key, file_path = service.resolve_batch_item_image_path(
        batch_task_id,
        item_id,
        kind=kind,
        visible_project_ids=principal.project_ids,
    )
    media_type = guess_media_type(file_path, object_key=object_key)
    filename = file_path.name if download else None
    return FileResponse(path=file_path, media_type=media_type, filename=filename)


@batch_inference_tasks_router.post(
    "/{batch_task_id}/cancel",
    response_model=BatchInferenceTaskResponse,
)
def cancel_batch_inference_task(
    batch_task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> BatchInferenceTaskResponse:
    """取消执行中的批量推理任务，未开始的子项标记为 cancelled。"""

    service = _build_batch_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    task = service.cancel_batch_task(
        batch_task_id,
        visible_project_ids=principal.project_ids,
    )
    return build_batch_inference_task_response(task)


@batch_inference_tasks_router.delete(
    "/{batch_task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_batch_inference_task(
    batch_task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> Response:
    """删除已结束的批量推理任务并同步清理产物文件；清理失败时保留记录以便重试。"""

    service = _build_batch_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    service.delete_batch_task(
        batch_task_id,
        visible_project_ids=principal.project_ids,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
