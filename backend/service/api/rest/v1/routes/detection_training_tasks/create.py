"""detection 训练任务创建 API。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.rest.v1.routes.training_execution_schemas import (
    merge_training_execution_options,
)
from backend.service.application.errors import ResourceNotFoundError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.queue.local_file import LocalFileQueueBackend

from .schemas import (
    DetectionTrainingTaskCreateRequestBody,
    DetectionTrainingTaskSubmissionResponse,
)
from .services import (
    _normalize_detection_training_model_type,
    _resolve_detection_training_service_and_request,
)

detection_training_create_router = APIRouter()


@detection_training_create_router.post(
    "/detection/training-tasks",
    response_model=DetectionTrainingTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_training_task(
    body: DetectionTrainingTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> DetectionTrainingTaskSubmissionResponse:
    """创建一个 detection 训练任务。"""

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的 Project",
            details={"project_id": body.project_id},
        )
    model_type = _normalize_detection_training_model_type(body.model_type)

    service_cls, request_cls = _resolve_detection_training_service_and_request(
        model_type
    )
    service = service_cls(
        session_factory=session_factory,
        queue_backend=queue_backend,
    )
    submission = service.submit_training_task(
        request_cls(
            project_id=body.project_id,
            dataset_export_id=body.dataset_export_id,
            dataset_export_manifest_key=body.dataset_export_manifest_key,
            recipe_id=body.recipe_id,
            model_scale=body.model_scale,
            output_model_name=body.output_model_name,
            warm_start_model_version_id=body.warm_start_model_version_id,
            evaluation_interval=body.execution.validation.interval_epochs,
            max_epochs=body.execution.max_epochs,
            batch_size=body.execution.fixed_batch_size,
            gpu_count=1,
            precision=body.execution.requested_precision,
            input_size=(
                body.execution.input_size.hw
                if body.execution.input_size is not None
                else None
            ),
            extra_options=merge_training_execution_options(
                execution=body.execution,
                model_options=body.parameters.to_execution_options(),
            ),
        ),
        created_by=principal.principal_id,
        display_name=body.display_name,
    )
    return DetectionTrainingTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        model_type=model_type,
        dataset_export_id=submission.dataset_export_id,
        dataset_export_manifest_key=submission.dataset_export_manifest_key,
        dataset_version_id=submission.dataset_version_id,
        format_id=submission.format_id,
    )
