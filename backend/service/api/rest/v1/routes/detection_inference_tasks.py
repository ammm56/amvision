"""detection inference tasks REST 路由。"""

from __future__ import annotations

from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.deps.detection_deployment_process_supervisor import (
    get_detection_async_inference_gateway_dispatcher_registry,
    get_detection_async_deployment_process_supervisor,
    get_detection_sync_deployment_process_supervisor,
)
from backend.service.api.rest.v1.routes.deployment_runtime_helpers import (
    ensure_requested_model_type_matches,
)
from backend.service.api.rest.v1.routes.detection_inference_helpers import (
    DetectionInferencePayloadResponse,
    DetectionInferenceTaskDetailResponse,
    DetectionInferenceTaskResultResponse,
    DetectionInferenceTaskSubmissionResponse,
    DetectionInferenceTaskSummaryResponse,
    _build_detection_inference_task_detail_response,
    _build_detection_inference_task_summary_response,
    _ensure_visible_detection_deployment,
    _matches_detection_inference_filters,
    _read_detection_async_inference_service_id,
    _read_detection_inference_request_payload,
    _require_running_detection_deployment_process,
    _resolve_detection_http_request_id,
    _resolve_detection_requested_score_threshold,
)
from backend.service.application.deployments.detection_deployment_service import (
    SqlAlchemyDetectionDeploymentService,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.models.inference.detection_inference_payloads import (
    DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE,
    attach_detection_inference_serialize_timing,
    build_detection_inference_payload,
    build_detection_prediction_request,
    normalize_detection_inference_input,
    serialize_detection_inference_payload,
)
from backend.service.application.models.inference.detection_inference_task_service import (
    DETECTION_INFERENCE_TASK_KIND,
    DetectionInferenceTaskRequest,
    SqlAlchemyDetectionInferenceTaskService,
    run_detection_inference_task,
)
from backend.service.application.models.inference.detection_async_inference_gateway import (
    DetectionAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_inference_tasks_router = APIRouter(prefix="/models", tags=["models"])


class DetectionInferenceTaskCreateRequestBody(BaseModel):
    """描述 detection 推理任务创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    deployment_instance_id: str = Field(description="执行推理使用的 DeploymentInstance id")
    model_type: str | None = Field(default=None, description="模型分类；提供时需与 DeploymentInstance 绑定模型一致")
    input_file_id: str | None = Field(default=None, description="Project 公开文件 id；与 input_uri、image_base64、input_image 四选一")
    input_uri: str | None = Field(default=None, description="输入图片 URI 或 object key")
    image_base64: str | None = Field(default=None, description="直接提交的 base64 图片内容")
    input_transport_mode: str = Field(default="storage", description="异步输入传输模式")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="推理阈值")
    save_result_image: bool = Field(default=True, description="是否输出预览图")
    return_preview_image_base64: bool = Field(default=False, description="是否在响应中直接返回预览图 base64")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加推理选项")
    display_name: str = Field(default="", description="可选展示名称")


class DetectionDirectInferenceRequestBody(BaseModel):
    """描述 detection 同步直返推理请求体。"""

    model_type: str | None = Field(default=None, description="模型分类；提供时需与 DeploymentInstance 绑定模型一致")
    input_file_id: str | None = Field(default=None, description="Project 公开文件 id；与 input_uri、image_base64、input_image 四选一")
    input_uri: str | None = Field(default=None, description="输入图片 URI 或 object key")
    image_base64: str | None = Field(default=None, description="直接提交的 base64 图片内容")
    input_transport_mode: str = Field(default="storage", description="同步输入传输模式")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="推理阈值")
    save_result_image: bool = Field(default=True, description="是否输出预览图")
    return_preview_image_base64: bool = Field(default=False, description="是否在响应中直接返回预览图 base64")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加推理选项")


@detection_inference_tasks_router.post(
    "/detection/inference-tasks",
    response_model=DetectionInferenceTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_detection_inference_task(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    deployment_process_supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[DetectionAsyncInferenceGatewayDispatcherRegistry, Depends(get_detection_async_inference_gateway_dispatcher_registry)],
) -> DetectionInferenceTaskSubmissionResponse:
    """创建一个正式 detection inference task。"""

    payload, input_source = await _read_detection_inference_request_payload(request)
    try:
        body = DetectionInferenceTaskCreateRequestBody.model_validate(payload)
    except Exception as error:
        raise InvalidRequestError(
            "推理任务创建请求不合法",
            details={"error": str(error)},
        ) from error
    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": body.project_id},
        )
    deployment_service = SqlAlchemyDetectionDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    deployment_view = deployment_service.get_deployment_instance(body.deployment_instance_id)
    if deployment_view.project_id != body.project_id:
        raise InvalidRequestError(
            "deployment_instance_id 与 project_id 不匹配",
            details={
                "project_id": body.project_id,
                "deployment_project_id": deployment_view.project_id,
                "deployment_instance_id": body.deployment_instance_id,
            },
        )
    process_config = deployment_service.resolve_process_config(body.deployment_instance_id)
    ensure_requested_model_type_matches(
        requested_model_type=body.model_type,
        resolved_model_type=process_config.runtime_target.model_type,
        deployment_instance_id=body.deployment_instance_id,
    )
    deployment_process_supervisor.ensure_deployment(process_config)
    _require_running_detection_deployment_process(
        deployment_process_supervisor=deployment_process_supervisor,
        process_config=process_config,
        runtime_mode="async",
    )
    normalized_input = normalize_detection_inference_input(
        dataset_storage=dataset_storage,
        request_id=_resolve_detection_http_request_id(request, prefix="inference-task-submit"),
        source=input_source,
        input_transport_mode=body.input_transport_mode,
        expected_project_id=body.project_id,
    )
    service = SqlAlchemyDetectionInferenceTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        deployment_process_supervisor=deployment_process_supervisor,
        async_inference_gateway_dispatcher_registry=gateway_dispatcher_registry,
    )
    submission = service.submit_inference_task(
        DetectionInferenceTaskRequest(
            project_id=body.project_id,
            deployment_instance_id=body.deployment_instance_id,
            model_type=body.model_type,
            input_file_id=body.input_file_id,
            input_uri=normalized_input.input_uri,
            input_source_kind=normalized_input.input_source_kind,
            input_transport_mode=normalized_input.input_transport_mode,
            input_image_bytes=normalized_input.input_image_bytes,
            async_inference_owner_id=_read_detection_async_inference_service_id(request),
            score_threshold=body.score_threshold,
            save_result_image=body.save_result_image,
            return_preview_image_base64=body.return_preview_image_base64,
            extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
        display_name=body.display_name,
    )
    return DetectionInferenceTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        deployment_instance_id=submission.deployment_instance_id,
        input_uri=submission.input_uri,
        input_source_kind=normalized_input.input_source_kind,
    )


@detection_inference_tasks_router.post(
    "/detection/deployment-instances/{deployment_instance_id}/infer",
    response_model=DetectionInferencePayloadResponse,
)
async def infer_detection_deployment_instance(
    deployment_instance_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    deployment_process_supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_detection_sync_deployment_process_supervisor)],
) -> DetectionInferencePayloadResponse:
    """直接执行一次同步 detection 推理并返回结果。"""

    payload, input_source = await _read_detection_inference_request_payload(request)
    payload.pop("project_id", None)
    payload.pop("deployment_instance_id", None)
    payload.pop("display_name", None)
    try:
        body = DetectionDirectInferenceRequestBody.model_validate(payload)
    except Exception as error:
        raise InvalidRequestError(
            "同步推理请求不合法",
            details={"error": str(error)},
        ) from error
    deployment_service = SqlAlchemyDetectionDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    deployment_view = deployment_service.get_deployment_instance(deployment_instance_id)
    _ensure_visible_detection_deployment(
        principal=principal,
        deployment_project_id=deployment_view.project_id,
        deployment_instance_id=deployment_instance_id,
    )
    process_config = deployment_service.resolve_process_config(deployment_instance_id)
    ensure_requested_model_type_matches(
        requested_model_type=body.model_type,
        resolved_model_type=process_config.runtime_target.model_type,
        deployment_instance_id=deployment_instance_id,
    )
    deployment_process_supervisor.ensure_deployment(process_config)
    _require_running_detection_deployment_process(
        deployment_process_supervisor=deployment_process_supervisor,
        process_config=process_config,
        runtime_mode="sync",
    )
    request_id = _resolve_detection_http_request_id(request, prefix="direct-inference")
    normalized_input = normalize_detection_inference_input(
        dataset_storage=dataset_storage,
        request_id=request_id,
        source=input_source,
        input_transport_mode=body.input_transport_mode,
        expected_project_id=deployment_view.project_id,
    )
    prediction_request = build_detection_prediction_request(
        normalized_input=normalized_input,
        score_threshold=_resolve_detection_requested_score_threshold(body.score_threshold),
        save_result_image=body.save_result_image,
        return_preview_image_base64=body.return_preview_image_base64,
        extra_options=dict(body.extra_options),
    )
    execution_result = run_detection_inference_task(
        deployment_process_supervisor=deployment_process_supervisor,
        process_config=process_config,
        input_uri=prediction_request.input_uri,
        input_image_bytes=prediction_request.input_image_bytes,
        input_image_payload=prediction_request.input_image_payload,
        score_threshold=prediction_request.score_threshold,
        save_result_image=prediction_request.save_result_image,
        return_preview_image_base64=body.return_preview_image_base64,
        extra_options=dict(prediction_request.extra_options),
    )
    output_prefix = f"runtime/direct-inference/{request_id}"
    preview_image_uri = None
    if body.save_result_image and execution_result.preview_image_bytes is not None:
        preview_image_uri = f"{output_prefix}/preview.jpg"
        dataset_storage.write_bytes(preview_image_uri, execution_result.preview_image_bytes)
    result_object_key = None
    if normalized_input.input_transport_mode == DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE:
        result_object_key = f"{output_prefix}/raw-result.json"
    serialize_started_at = perf_counter()
    response_payload = build_detection_inference_payload(
        request_id=request_id,
        inference_task_id=None,
        deployment_instance_id=deployment_instance_id,
        instance_id=execution_result.instance_id,
        runtime_target=process_config.runtime_target,
        normalized_input=normalized_input,
        score_threshold=_resolve_detection_requested_score_threshold(body.score_threshold),
        save_result_image=body.save_result_image,
        return_preview_image_base64=body.return_preview_image_base64,
        execution_result=execution_result,
        preview_image_uri=preview_image_uri,
        result_object_key=result_object_key,
    )
    serialized_payload = serialize_detection_inference_payload(response_payload)
    serialized_payload = attach_detection_inference_serialize_timing(
        payload=serialized_payload,
        serialize_ms=(perf_counter() - serialize_started_at) * 1000,
    )
    if result_object_key is not None:
        dataset_storage.write_json(result_object_key, serialized_payload)
    return DetectionInferencePayloadResponse.model_validate(serialized_payload)


@detection_inference_tasks_router.get(
    "/detection/inference-tasks",
    response_model=list[DetectionInferenceTaskSummaryResponse],
)
def list_detection_inference_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    state: Annotated[str | None, Query(description="任务状态")] = None,
    created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
    deployment_instance_id: Annotated[str | None, Query(description="DeploymentInstance id")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[DetectionInferenceTaskSummaryResponse]:
    """按公开筛选条件列出 detection 推理任务。"""

    visible_project_ids = []
    if project_id is not None:
        if principal.project_ids and project_id not in principal.project_ids:
            raise PermissionDeniedError(
                "当前主体无权访问该 Project",
                details={"project_id": project_id},
            )
        visible_project_ids.append(project_id)
    elif principal.project_ids:
        visible_project_ids.extend(principal.project_ids)
    else:
        raise InvalidRequestError("查询推理任务列表时必须提供 project_id")

    service = SqlAlchemyTaskService(session_factory)
    matched_tasks = []
    for current_project_id in visible_project_ids:
        matched_tasks.extend(
            service.list_tasks(
                TaskQueryFilters(
                    project_id=current_project_id,
                    task_kind=DETECTION_INFERENCE_TASK_KIND,
                    state=state,
                    created_by=created_by,
                    limit=limit,
                )
            )
        )
    visible_tasks = [
        task
        for task in matched_tasks
        if _matches_detection_inference_filters(
            task=task,
            deployment_instance_id=deployment_instance_id,
        )
    ]
    visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
    return [_build_detection_inference_task_summary_response(task) for task in visible_tasks[:limit]]


@detection_inference_tasks_router.get(
    "/detection/inference-tasks/{task_id}",
    response_model=DetectionInferenceTaskDetailResponse,
)
def get_detection_inference_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    include_events: Annotated[bool, Query(description="是否返回事件列表")] = False,
) -> DetectionInferenceTaskDetailResponse:
    """按任务 id 返回 detection 推理任务详情。"""

    task_detail = _require_visible_detection_inference_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=include_events,
    )
    return _build_detection_inference_task_detail_response(task_detail.task, tuple(task_detail.events))


@detection_inference_tasks_router.get(
    "/detection/inference-tasks/{task_id}/result",
    response_model=DetectionInferenceTaskResultResponse,
)
def get_detection_inference_task_result(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionInferenceTaskResultResponse:
    """按任务 id 返回当前 detection 推理结果。"""

    task_detail = _require_visible_detection_inference_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    result = dict(task_detail.task.result)
    object_key = result.get("result_object_key")
    if not isinstance(object_key, str) or not object_key.strip():
        if task_detail.task.state in {"queued", "running"}:
            return DetectionInferenceTaskResultResponse(
                file_status="pending",
                task_state=task_detail.task.state,
                object_key=None,
                payload={},
            )
        raise InvalidRequestError(
            "当前推理任务缺少结果文件",
            details={"task_id": task_id},
        )
    resolved_path = dataset_storage.resolve(object_key)
    if not resolved_path.is_file():
        if task_detail.task.state in {"queued", "running"}:
            return DetectionInferenceTaskResultResponse(
                file_status="pending",
                task_state=task_detail.task.state,
                object_key=object_key,
                payload={},
            )
        raise InvalidRequestError(
            "当前推理任务的结果文件不存在",
            details={"task_id": task_id, "object_key": object_key},
        )
    payload = dataset_storage.read_json(object_key)
    return DetectionInferenceTaskResultResponse(
        file_status="ready",
        task_state=task_detail.task.state,
        object_key=object_key,
        payload=dict(payload) if isinstance(payload, dict) else {},
    )
def _require_visible_detection_inference_task(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    include_events: bool,
):
    """读取并校验当前主体可见的 detection 推理任务。"""

    service = SqlAlchemyTaskService(session_factory)
    task_detail = service.get_task(task_id, include_events=include_events)
    project_id = task_detail.task.project_id
    if principal.project_ids and project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的推理任务",
            details={"task_id": task_id},
        )
    if task_detail.task.task_kind != DETECTION_INFERENCE_TASK_KIND:
        raise ResourceNotFoundError(
            "找不到指定的 detection 推理任务",
            details={"task_id": task_id},
        )
    return task_detail
