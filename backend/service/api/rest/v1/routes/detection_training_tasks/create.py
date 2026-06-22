"""detection 训练任务创建 API。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.application.errors import ResourceNotFoundError
from backend.service.infrastructure.db.session import SessionFactory

from .schemas import DetectionTrainingTaskCreateRequestBody, DetectionTrainingTaskSubmissionResponse
from .services import _DETECTION_TRAINING_SERVICE_BY_MODEL_TYPE, _normalize_detection_training_model_type


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

    service_cls, request_cls = _DETECTION_TRAINING_SERVICE_BY_MODEL_TYPE[model_type]
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
            evaluation_interval=body.evaluation_interval,
            max_epochs=body.max_epochs,
            batch_size=body.batch_size,
            gpu_count=body.gpu_count,
            precision=body.precision,
            input_size=body.input_size,
            extra_options=body.extra_options.model_dump(exclude_none=True),
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
