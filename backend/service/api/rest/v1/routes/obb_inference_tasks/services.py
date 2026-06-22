"""obb inference route service 装配与执行编排。"""

from __future__ import annotations

from time import perf_counter

from fastapi import Request

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.api.rest.v1.routes.task_deployments.runtime_controls import (
    ensure_deployment_visible,
    ensure_requested_model_type_matches,
    read_async_inference_service_id,
    require_running_deployment_process,
)
from backend.service.api.rest.v1.routes.obb_inference_tasks.responses import (
    ObbInferenceTaskSubmissionResponse,
)
from backend.service.api.rest.v1.routes.obb_inference_tasks.schemas import (
    ObbDirectInferenceRequestBody,
    ObbInferenceTaskCreateRequestBody,
)
from backend.service.api.rest.v1.routes.task_inference.requests import (
    read_inference_http_payload,
    resolve_inference_http_request_id,
)
from backend.service.api.rest.v1.routes.task_inference.responses import (
    InferenceTaskDetailResponse,
    InferenceTaskResultResponse,
    InferenceTaskSummaryResponse,
)
from backend.service.api.rest.v1.routes.task_inference.visibility import (
    get_inference_task_detail_response,
    get_inference_task_result_response,
    list_inference_task_summaries,
)
from backend.service.application.deployments.obb_deployment_service import (
    SqlAlchemyObbDeploymentService,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError
from backend.service.application.models.inference.obb_async_inference_gateway import (
    ObbAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.models.inference.obb_inference_payloads import (
    OBB_INFERENCE_INPUT_TRANSPORT_STORAGE,
    ObbInferenceInputSource,
    attach_obb_inference_serialize_timing,
    build_obb_inference_payload,
    build_obb_prediction_request,
    normalize_obb_inference_input,
    serialize_obb_inference_payload,
)
from backend.service.application.models.inference.obb_inference_task_service import (
    OBB_INFERENCE_TASK_KIND,
    ObbInferenceTaskRequest,
    SqlAlchemyObbInferenceTaskService,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


async def submit_obb_inference_task_from_request(
    *,
    request: Request,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    queue_backend: LocalFileQueueBackend,
    dataset_storage: LocalDatasetStorage,
    deployment_process_supervisor: DeploymentProcessSupervisor,
    gateway_dispatcher_registry: ObbAsyncInferenceGatewayDispatcherRegistry,
) -> ObbInferenceTaskSubmissionResponse:
    """从 HTTP 请求创建 obb inference task。"""

    payload, source_payload = await read_inference_http_payload(request)
    try:
        body = ObbInferenceTaskCreateRequestBody.model_validate(payload)
    except Exception as error:
        raise InvalidRequestError("obb 推理任务请求格式无效", details={"error": str(error)}) from error

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project", details={"project_id": body.project_id})

    deployment_service = build_obb_deployment_service(
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
    normalized_input = normalize_obb_inference_input(
        dataset_storage=dataset_storage,
        request_id=resolve_inference_http_request_id(request, prefix="obb-inference-task"),
        source=ObbInferenceInputSource(**source_payload),
        input_transport_mode=body.input_transport_mode,
        expected_project_id=body.project_id,
    )
    submission = SqlAlchemyObbInferenceTaskService(
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        deployment_process_supervisor=deployment_process_supervisor,
        async_inference_gateway_dispatcher_registry=gateway_dispatcher_registry,
    ).submit_inference_task(
        ObbInferenceTaskRequest(
            project_id=body.project_id,
            deployment_instance_id=body.deployment_instance_id,
            model_type=body.model_type,
            input_file_id=normalized_input.input_file_id,
            input_uri=normalized_input.input_uri,
            input_source_kind=normalized_input.input_source_kind,
            input_transport_mode=normalized_input.input_transport_mode,
            input_image_bytes=normalized_input.input_image_bytes,
            async_inference_owner_id=read_async_inference_service_id(request, task_type="obb"),
            score_threshold=body.score_threshold,
            save_result_image=body.save_result_image,
            return_preview_image_base64=body.return_preview_image_base64,
            extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
        display_name=body.display_name,
    )
    return ObbInferenceTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        deployment_instance_id=submission.deployment_instance_id,
        input_uri=submission.input_uri,
        input_source_kind=normalized_input.input_source_kind,
    )


async def infer_obb_deployment_instance_from_request(
    *,
    deployment_instance_id: str,
    request: Request,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    deployment_process_supervisor: DeploymentProcessSupervisor,
) -> dict[str, object]:
    """直接执行一次同步 obb 推理并返回结果。"""

    payload, source_payload = await read_inference_http_payload(request)
    payload.pop("project_id", None)
    payload.pop("deployment_instance_id", None)
    payload.pop("display_name", None)
    try:
        body = ObbDirectInferenceRequestBody.model_validate(payload)
    except Exception as error:
        raise InvalidRequestError("obb 同步推理请求不合法", details={"error": str(error)}) from error

    deployment_service = build_obb_deployment_service(
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
    request_id = resolve_inference_http_request_id(request, prefix="obb-direct-inference")
    normalized_input = normalize_obb_inference_input(
        dataset_storage=dataset_storage,
        request_id=request_id,
        source=ObbInferenceInputSource(**source_payload),
        input_transport_mode=body.input_transport_mode,
        expected_project_id=deployment_view.project_id,
    )
    resolved_score_threshold = (
        float(body.score_threshold)
        if isinstance(body.score_threshold, int | float)
        else 0.3
    )
    prediction_request = build_obb_prediction_request(
        normalized_input=normalized_input,
        score_threshold=resolved_score_threshold,
        save_result_image=body.save_result_image,
        return_preview_image_base64=body.return_preview_image_base64,
        extra_options=dict(body.extra_options),
    )
    execution = deployment_process_supervisor.run_inference(config=process_config, request=prediction_request)
    output_prefix = f"runtime/direct-inference/{request_id}"
    preview_image_uri = None
    if body.save_result_image and execution.execution_result.preview_image_bytes is not None:
        preview_image_uri = f"{output_prefix}/preview.jpg"
        dataset_storage.write_bytes(preview_image_uri, execution.execution_result.preview_image_bytes)
    result_object_key = None
    if normalized_input.input_transport_mode == OBB_INFERENCE_INPUT_TRANSPORT_STORAGE:
        result_object_key = f"{output_prefix}/raw-result.json"
    serialize_started_at = perf_counter()
    serialized_payload = serialize_obb_inference_payload(
        build_obb_inference_payload(
            request_id=request_id,
            inference_task_id=None,
            deployment_instance_id=deployment_instance_id,
            instance_id=execution.instance_id,
            runtime_target=process_config.runtime_target,
            normalized_input=normalized_input,
            score_threshold=resolved_score_threshold,
            save_result_image=body.save_result_image,
            return_preview_image_base64=body.return_preview_image_base64,
            execution_result=execution.execution_result,
            preview_image_uri=preview_image_uri,
            result_object_key=result_object_key,
        )
    )
    serialized_payload = attach_obb_inference_serialize_timing(
        payload=serialized_payload,
        serialize_ms=(perf_counter() - serialize_started_at) * 1000,
    )
    if result_object_key is not None:
        dataset_storage.write_json(result_object_key, serialized_payload)
    return serialized_payload


def list_obb_inference_task_summaries(
    *,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    project_id: str | None,
    state: str | None,
    created_by: str | None,
    deployment_instance_id: str | None,
    limit: int,
) -> list[InferenceTaskSummaryResponse]:
    """按公开筛选条件列出 obb 推理任务。"""

    return list_inference_task_summaries(
        principal=principal,
        session_factory=session_factory,
        task_kind=OBB_INFERENCE_TASK_KIND,
        project_id=project_id,
        state=state,
        created_by=created_by,
        deployment_instance_id=deployment_instance_id,
        limit=limit,
    )


def get_obb_inference_task_detail_response(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    include_events: bool,
) -> InferenceTaskDetailResponse:
    """按任务 id 返回 obb 推理任务详情。"""

    return get_inference_task_detail_response(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        task_kind=OBB_INFERENCE_TASK_KIND,
        resource_label="obb 推理任务",
        include_events=include_events,
    )


def get_obb_inference_task_result_response(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> InferenceTaskResultResponse:
    """按任务 id 返回当前 obb 推理结果。"""

    return get_inference_task_result_response(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        task_kind=OBB_INFERENCE_TASK_KIND,
        resource_label="obb 推理任务",
    )


def build_obb_deployment_service(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> SqlAlchemyObbDeploymentService:
    """构建 obb deployment 公共服务。"""

    return SqlAlchemyObbDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
