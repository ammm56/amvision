"""classification inference tasks REST 路由。"""

from __future__ import annotations

from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.classification_deployment_process_supervisor import (
    get_classification_async_deployment_process_supervisor,
    get_classification_async_inference_gateway_dispatcher_registry,
    get_classification_sync_deployment_process_supervisor,
)
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.deployment_runtime_helpers import (
    ensure_deployment_visible,
    ensure_requested_model_type_matches,
    read_async_inference_service_id,
    require_running_deployment_process,
)
from backend.service.api.rest.v1.routes.inference_route_helpers import (
    InferenceTaskDetailResponse,
    InferenceTaskResultResponse,
    InferenceTaskSummaryResponse,
    build_inference_task_detail_response,
    build_inference_task_summary_response,
    read_inference_http_payload,
    read_inference_task_result,
    require_visible_inference_task,
    resolve_inference_http_request_id,
)
from backend.service.application.deployments.classification_deployment_service import (
    SqlAlchemyClassificationDeploymentService,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError
from backend.service.application.models.classification_async_inference_gateway import (
    ClassificationAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.models.classification_inference_payloads import (
    CLASSIFICATION_INFERENCE_INPUT_TRANSPORT_STORAGE,
    ClassificationInferenceInputSource,
    attach_classification_inference_serialize_timing,
    build_classification_inference_payload,
    build_classification_prediction_request,
    normalize_classification_inference_input,
    serialize_classification_inference_payload,
)
from backend.service.application.models.classification_inference_task_service import (
    CLASSIFICATION_INFERENCE_TASK_KIND,
    ClassificationInferenceTaskRequest,
    SqlAlchemyClassificationInferenceTaskService,
)
from backend.service.application.runtime.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


classification_inference_tasks_router = APIRouter(prefix="/models", tags=["models"])


class ClassificationInferenceTaskCreateRequestBody(BaseModel):
    """描述 classification 异步推理任务创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    deployment_instance_id: str = Field(description="执行推理使用的 DeploymentInstance id")
    model_type: str | None = Field(default=None, description="模型分类；提供时需与 DeploymentInstance 绑定模型一致")
    input_file_id: str | None = Field(default=None, description="Project 公开文件 id")
    input_uri: str | None = Field(default=None, description="输入图片 URI 或 object key")
    image_base64: str | None = Field(default=None, description="直接提交的 base64 图片内容")
    input_transport_mode: str = Field(default="storage", description="输入传输模式")
    top_k: int = Field(default=5, ge=1, description="返回 top-k 分类结果")
    save_result_image: bool = Field(default=False, description="是否输出预览图")
    return_preview_image_base64: bool = Field(default=False, description="是否直接返回预览图 base64")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加推理选项")
    display_name: str = Field(default="", description="可选展示名称")


class ClassificationDirectInferenceRequestBody(BaseModel):
    """描述 classification 同步直返推理请求体。"""

    model_type: str | None = Field(default=None, description="模型分类；提供时需与 DeploymentInstance 绑定模型一致")
    input_file_id: str | None = Field(default=None, description="Project 公开文件 id")
    input_uri: str | None = Field(default=None, description="输入图片 URI 或 object key")
    image_base64: str | None = Field(default=None, description="直接提交的 base64 图片内容")
    input_transport_mode: str = Field(default="storage", description="输入传输模式")
    top_k: int = Field(default=5, ge=1, description="返回 top-k 分类结果")
    save_result_image: bool = Field(default=False, description="是否输出预览图")
    return_preview_image_base64: bool = Field(default=False, description="是否直接返回预览图 base64")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加推理选项")


class ClassificationInferenceTaskSubmissionResponse(BaseModel):
    """描述 classification 推理任务创建响应。"""

    task_id: str = Field(description="任务 id")
    status: str = Field(description="当前状态")
    queue_name: str = Field(description="队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    deployment_instance_id: str = Field(description="DeploymentInstance id")
    input_uri: str = Field(description="标准化输入 URI")
    input_source_kind: str = Field(description="输入来源类型")


@classification_inference_tasks_router.post(
    "/classification/inference-tasks",
    response_model=ClassificationInferenceTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_classification_inference_task(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    deployment_process_supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[ClassificationAsyncInferenceGatewayDispatcherRegistry, Depends(get_classification_async_inference_gateway_dispatcher_registry)],
) -> ClassificationInferenceTaskSubmissionResponse:
    """创建一条 classification 异步推理任务。"""

    payload, source_payload = await read_inference_http_payload(request)
    try:
        body = ClassificationInferenceTaskCreateRequestBody.model_validate(payload)
    except Exception as error:
        raise InvalidRequestError(
            "classification 推理任务请求格式无效",
            details={"error": str(error)},
        ) from error

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": body.project_id},
        )

    deployment_service = _build_classification_deployment_service(
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
    require_running_deployment_process(
        deployment_process_supervisor=deployment_process_supervisor,
        process_config=process_config,
        runtime_mode="async",
    )
    normalized_input = normalize_classification_inference_input(
        dataset_storage=dataset_storage,
        request_id=resolve_inference_http_request_id(
            request,
            prefix="classification-inference-task",
        ),
        source=ClassificationInferenceInputSource(**source_payload),
        input_transport_mode=body.input_transport_mode,
        expected_project_id=body.project_id,
    )
    submission = SqlAlchemyClassificationInferenceTaskService(
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        deployment_process_supervisor=deployment_process_supervisor,
        async_inference_gateway_dispatcher_registry=gateway_dispatcher_registry,
    ).submit_inference_task(
        ClassificationInferenceTaskRequest(
            project_id=body.project_id,
            deployment_instance_id=body.deployment_instance_id,
            model_type=body.model_type,
            input_file_id=normalized_input.input_file_id,
            input_uri=normalized_input.input_uri,
            input_source_kind=normalized_input.input_source_kind,
            input_transport_mode=normalized_input.input_transport_mode,
            input_image_bytes=normalized_input.input_image_bytes,
            async_inference_owner_id=read_async_inference_service_id(
                request,
                task_type="classification",
            ),
            top_k=body.top_k,
            save_result_image=body.save_result_image,
            return_preview_image_base64=body.return_preview_image_base64,
            extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
        display_name=body.display_name,
    )
    return ClassificationInferenceTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        deployment_instance_id=submission.deployment_instance_id,
        input_uri=submission.input_uri,
        input_source_kind=normalized_input.input_source_kind,
    )


@classification_inference_tasks_router.post(
    "/classification/deployment-instances/{deployment_instance_id}/infer",
    response_model=dict[str, object],
)
async def infer_classification_deployment_instance(
    deployment_instance_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    deployment_process_supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_sync_deployment_process_supervisor)],
) -> dict[str, object]:
    """直接执行一次同步 classification 推理并返回结果。"""

    payload, source_payload = await read_inference_http_payload(request)
    payload.pop("project_id", None)
    payload.pop("deployment_instance_id", None)
    payload.pop("display_name", None)
    try:
        body = ClassificationDirectInferenceRequestBody.model_validate(payload)
    except Exception as error:
        raise InvalidRequestError(
            "classification 同步推理请求不合法",
            details={"error": str(error)},
        ) from error

    deployment_service = _build_classification_deployment_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    deployment_view = deployment_service.get_deployment_instance(deployment_instance_id)
    ensure_deployment_visible(
        principal=principal,
        project_id=deployment_view.project_id,
        deployment_instance_id=deployment_instance_id,
    )
    process_config = deployment_service.resolve_process_config(deployment_instance_id)
    ensure_requested_model_type_matches(
        requested_model_type=body.model_type,
        resolved_model_type=process_config.runtime_target.model_type,
        deployment_instance_id=deployment_instance_id,
    )
    deployment_process_supervisor.ensure_deployment(process_config)
    require_running_deployment_process(
        deployment_process_supervisor=deployment_process_supervisor,
        process_config=process_config,
        runtime_mode="sync",
    )
    request_id = resolve_inference_http_request_id(
        request,
        prefix="classification-direct-inference",
    )
    normalized_input = normalize_classification_inference_input(
        dataset_storage=dataset_storage,
        request_id=request_id,
        source=ClassificationInferenceInputSource(**source_payload),
        input_transport_mode=body.input_transport_mode,
        expected_project_id=deployment_view.project_id,
    )
    prediction_request = build_classification_prediction_request(
        normalized_input=normalized_input,
        top_k=body.top_k,
        save_result_image=body.save_result_image,
        return_preview_image_base64=body.return_preview_image_base64,
        extra_options=dict(body.extra_options),
    )
    execution = deployment_process_supervisor.run_inference(
        config=process_config,
        request=prediction_request,
    )
    output_prefix = f"runtime/direct-inference/{request_id}"
    preview_image_uri = None
    if body.save_result_image and execution.execution_result.preview_image_bytes is not None:
        preview_image_uri = f"{output_prefix}/preview.jpg"
        dataset_storage.write_bytes(preview_image_uri, execution.execution_result.preview_image_bytes)
    result_object_key = None
    if normalized_input.input_transport_mode == CLASSIFICATION_INFERENCE_INPUT_TRANSPORT_STORAGE:
        result_object_key = f"{output_prefix}/raw-result.json"
    serialize_started_at = perf_counter()
    serialized_payload = serialize_classification_inference_payload(
        build_classification_inference_payload(
            request_id=request_id,
            inference_task_id=None,
            deployment_instance_id=deployment_instance_id,
            instance_id=execution.instance_id,
            runtime_target=process_config.runtime_target,
            normalized_input=normalized_input,
            top_k=body.top_k,
            save_result_image=body.save_result_image,
            return_preview_image_base64=body.return_preview_image_base64,
            execution_result=execution.execution_result,
            preview_image_uri=preview_image_uri,
            result_object_key=result_object_key,
        )
    )
    serialized_payload = attach_classification_inference_serialize_timing(
        payload=serialized_payload,
        serialize_ms=(perf_counter() - serialize_started_at) * 1000,
    )
    if result_object_key is not None:
        dataset_storage.write_json(result_object_key, serialized_payload)
    return serialized_payload


@classification_inference_tasks_router.get(
    "/classification/inference-tasks",
    response_model=list[InferenceTaskSummaryResponse],
)
def list_classification_inference_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    state: Annotated[str | None, Query(description="任务状态")] = None,
    created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
    deployment_instance_id: Annotated[str | None, Query(description="DeploymentInstance id")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[InferenceTaskSummaryResponse]:
    """按公开筛选条件列出 classification 推理任务。"""

    visible_project_ids = _resolve_visible_project_ids(
        principal=principal,
        project_id=project_id,
    )
    service = SqlAlchemyTaskService(session_factory)
    matched_tasks = []
    for current_project_id in visible_project_ids:
        matched_tasks.extend(
            service.list_tasks(
                TaskQueryFilters(
                    project_id=current_project_id,
                    task_kind=CLASSIFICATION_INFERENCE_TASK_KIND,
                    state=state,
                    created_by=created_by,
                    limit=limit,
                )
            )
        )
    visible_tasks = [
        task
        for task in matched_tasks
        if _matches_deployment_instance(task=task, deployment_instance_id=deployment_instance_id)
    ]
    visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
    return [build_inference_task_summary_response(task) for task in visible_tasks[:limit]]


@classification_inference_tasks_router.get(
    "/classification/inference-tasks/{task_id}",
    response_model=InferenceTaskDetailResponse,
)
def get_classification_inference_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    include_events: Annotated[bool, Query(description="是否返回事件列表")] = False,
) -> InferenceTaskDetailResponse:
    """按任务 id 返回 classification 推理任务详情。"""

    task_detail = require_visible_inference_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        task_kind=CLASSIFICATION_INFERENCE_TASK_KIND,
        resource_label="classification 推理任务",
        include_events=include_events,
    )
    return build_inference_task_detail_response(task_detail.task, tuple(task_detail.events))


@classification_inference_tasks_router.get(
    "/classification/inference-tasks/{task_id}/result",
    response_model=InferenceTaskResultResponse,
)
def get_classification_inference_task_result(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> InferenceTaskResultResponse:
    """按任务 id 返回当前 classification 推理结果。"""

    task_detail = require_visible_inference_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        task_kind=CLASSIFICATION_INFERENCE_TASK_KIND,
        resource_label="classification 推理任务",
        include_events=False,
    )
    return read_inference_task_result(
        task_state=task_detail.task.state,
        result_payload=dict(task_detail.task.result),
        dataset_storage=dataset_storage,
    )


def _build_classification_deployment_service(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> SqlAlchemyClassificationDeploymentService:
    """构建 classification deployment 公共服务。"""

    return SqlAlchemyClassificationDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


def _resolve_visible_project_ids(
    *,
    principal: AuthenticatedPrincipal,
    project_id: str | None,
) -> list[str]:
    """解析当前查询允许访问的项目列表。"""

    visible_project_ids: list[str] = []
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
    return visible_project_ids


def _matches_deployment_instance(*, task: object, deployment_instance_id: str | None) -> bool:
    """判断推理任务是否满足 deployment_instance_id 过滤条件。"""

    if deployment_instance_id is None:
        return True
    task_spec = dict(task.task_spec)
    return task_spec.get("deployment_instance_id") == deployment_instance_id
