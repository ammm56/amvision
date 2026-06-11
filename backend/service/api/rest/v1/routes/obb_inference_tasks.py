"""obb inference tasks REST 路由。"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.obb_deployment_process_supervisor import (
    get_obb_async_deployment_process_supervisor,
    get_obb_async_inference_gateway_dispatcher_registry,
)
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.deployment_runtime_helpers import (
    ensure_requested_model_type_matches,
    read_async_inference_service_id,
    require_running_deployment_process,
)
from backend.service.application.deployments.obb_deployment_service import (
    SqlAlchemyObbDeploymentService,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError
from backend.service.application.models.obb_async_inference_gateway import (
    ObbAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.models.obb_inference_payloads import (
    ObbInferenceInputSource,
    normalize_obb_inference_input,
)
from backend.service.application.models.obb_inference_task_service import (
    ObbInferenceTaskRequest,
    SqlAlchemyObbInferenceTaskService,
)
from backend.service.application.runtime.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


obb_inference_tasks_router = APIRouter(prefix="/models", tags=["models"])


class ObbInferenceTaskCreateRequestBody(BaseModel):
    project_id: str = Field(description="所属 Project id")
    deployment_instance_id: str = Field(description="DeploymentInstance id")
    model_type: str = Field(description="模型分类")
    input_file_id: str | None = Field(default=None)
    input_uri: str | None = Field(default=None)
    image_base64: str | None = Field(default=None)
    input_transport_mode: str = Field(default="storage")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    save_result_image: bool = Field(default=False)
    return_preview_image_base64: bool = Field(default=False)
    extra_options: dict[str, object] = Field(default_factory=dict)
    display_name: str = Field(default="")


class ObbInferenceTaskSubmissionResponse(BaseModel):
    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    deployment_instance_id: str
    input_uri: str
    input_source_kind: str


@obb_inference_tasks_router.post(
    "/obb/inference-tasks",
    response_model=ObbInferenceTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_obb_inference_task(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    deployment_process_supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_obb_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[ObbAsyncInferenceGatewayDispatcherRegistry, Depends(get_obb_async_inference_gateway_dispatcher_registry)],
) -> ObbInferenceTaskSubmissionResponse:
    """创建一条 obb 异步推理任务。"""

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        raw_payload = form.get("payload")
        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else {}
    else:
        body_bytes = await request.body()
        payload = json.loads(body_bytes) if body_bytes else {}

    try:
        body = ObbInferenceTaskCreateRequestBody.model_validate(payload)
    except Exception as error:
        raise InvalidRequestError("obb 推理任务请求格式无效", details={"error": str(error)}) from error

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project", details={"project_id": body.project_id})

    deployment_service = SqlAlchemyObbDeploymentService(
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
    normalized = normalize_obb_inference_input(
        dataset_storage=dataset_storage,
        request_id=f"obb-inference-task-{body.deployment_instance_id}",
        source=ObbInferenceInputSource(
            input_file_id=body.input_file_id,
            input_uri=body.input_uri,
            image_base64=body.image_base64,
        ),
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
            input_file_id=normalized.input_file_id,
            input_uri=normalized.input_uri,
            input_source_kind=normalized.input_source_kind,
            input_transport_mode=normalized.input_transport_mode,
            input_image_bytes=normalized.input_image_bytes,
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
        input_source_kind=normalized.input_source_kind,
    )
