"""detection 训练任务控制 API。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.yolox_detection_task_service import SqlAlchemyYoloXTrainingTaskService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

from .responses import (
    DetectionTrainingTaskDetailResponse,
    _build_detection_training_task_detail_response,
)
from .schemas import DetectionTrainingTaskSubmissionResponse
from .services import (
    _build_detection_training_service_for_task,
    _require_visible_detection_training_task,
    _resolve_detection_training_model_type_from_task,
)

detection_training_control_router = APIRouter()


@detection_training_control_router.post(
    "/detection/training-tasks/{task_id}/save",
    response_model=DetectionTrainingTaskDetailResponse,
)
def request_detection_training_save(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> DetectionTrainingTaskDetailResponse:
    """为运行中的 detection 训练任务请求一次手动保存。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = _build_detection_training_service_for_task(
        task=task_detail.task,
        session_factory=session_factory,
    )
    updated_task_detail = service.request_training_save(task_id, requested_by=principal.principal_id)
    return _build_detection_training_task_detail_response(
        updated_task_detail.task,
        tuple(updated_task_detail.events),
    )


@detection_training_control_router.post(
    "/detection/training-tasks/{task_id}/pause",
    response_model=DetectionTrainingTaskDetailResponse,
)
def request_detection_training_pause(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> DetectionTrainingTaskDetailResponse:
    """为运行中的 detection 训练任务请求暂停。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = _build_detection_training_service_for_task(
        task=task_detail.task,
        session_factory=session_factory,
    )
    updated_task_detail = service.request_training_pause(task_id, requested_by=principal.principal_id)
    return _build_detection_training_task_detail_response(
        updated_task_detail.task,
        tuple(updated_task_detail.events),
    )


@detection_training_control_router.post(
    "/detection/training-tasks/{task_id}/resume",
    response_model=DetectionTrainingTaskSubmissionResponse,
)
def resume_detection_training_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> DetectionTrainingTaskSubmissionResponse:
    """把一个 paused 的 detection 训练任务重新入队执行。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = _build_detection_training_service_for_task(
        task=task_detail.task,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    submission = service.resume_training_task(task_id, resumed_by=principal.principal_id)
    return DetectionTrainingTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        model_type=_resolve_detection_training_model_type_from_task(task_detail.task),
        dataset_export_id=submission.dataset_export_id,
        dataset_export_manifest_key=submission.dataset_export_manifest_key,
        dataset_version_id=submission.dataset_version_id,
        format_id=submission.format_id,
    )


@detection_training_control_router.post(
    "/detection/training-tasks/{task_id}/terminate",
    response_model=DetectionTrainingTaskDetailResponse,
)
def terminate_detection_training_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> DetectionTrainingTaskDetailResponse:
    """请求终止一个 queued、running 或 paused 的 detection 训练任务。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = _build_detection_training_service_for_task(
        task=task_detail.task,
        session_factory=session_factory,
    )
    updated_task_detail = service.request_training_terminate(task_id, requested_by=principal.principal_id)
    return _build_detection_training_task_detail_response(
        updated_task_detail.task,
        tuple(updated_task_detail.events),
    )


@detection_training_control_router.delete(
    "/detection/training-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_detection_training_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> Response:
    """删除一个已经停止且可安全删除的 detection 训练任务。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = _build_detection_training_service_for_task(
        task=task_detail.task,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    service.delete_training_task(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@detection_training_control_router.post(
    "/detection/training-tasks/{task_id}/register-model-version",
    response_model=DetectionTrainingTaskDetailResponse,
)
def register_detection_training_latest_checkpoint_model_version(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionTrainingTaskDetailResponse:
    """把当前训练任务 latest checkpoint 手动登记为一个新的 ModelVersion。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    model_type = _resolve_detection_training_model_type_from_task(task_detail.task)
    if model_type != "yolox":
        raise InvalidRequestError(
            "当前模型分类尚未接通 latest checkpoint 手动登记",
            details={"task_id": task_id, "model_type": model_type},
        )
    service = SqlAlchemyYoloXTrainingTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    updated_task_detail = service.register_latest_checkpoint_model_version(
        task_id,
        registered_by=principal.principal_id,
    )
    return _build_detection_training_task_detail_response(
        updated_task_detail.task,
        tuple(updated_task_detail.events),
    )

