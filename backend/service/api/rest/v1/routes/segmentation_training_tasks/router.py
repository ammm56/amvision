"""segmentation training task REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.segmentation_training_tasks.controls import (
    delete_training_task,
    get_training_task_detail,
    list_training_tasks,
    request_training_control,
    resume_training_task,
)
from backend.service.api.rest.v1.routes.segmentation_training_tasks.responses import (
    TrainingTaskDetailResponse,
    TrainingTaskSubmissionResponse,
    TrainingTaskSummaryResponse,
)
from backend.service.api.rest.v1.routes.segmentation_training_tasks.schemas import (
    SegmentationTrainingTaskCreateRequestBody,
    SegmentationTrainingTaskSubmissionResponse,
)
from backend.service.api.rest.v1.routes.segmentation_training_tasks.services import (
    submit_segmentation_training_task,
)
from backend.service.api.rest.v1.routes.task_training.services import (
    require_project_access,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


segmentation_training_tasks_router = APIRouter(prefix="/models", tags=["models"])


@segmentation_training_tasks_router.post(
    "/segmentation/training-tasks",
    response_model=SegmentationTrainingTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_segmentation_training_task(
    body: SegmentationTrainingTaskCreateRequestBody,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))
    ],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> SegmentationTrainingTaskSubmissionResponse:
    """创建 segmentation 训练任务。"""

    require_project_access(
        principal_project_ids=principal.project_ids,
        project_id=body.project_id,
    )
    return submit_segmentation_training_task(
        body=body,
        created_by=principal.principal_id,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@segmentation_training_tasks_router.get(
    "/segmentation/training-tasks",
    response_model=list[TrainingTaskSummaryResponse],
)
def list_segmentation_training_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str, Query(description="所属 Project id")],
    model_type: Annotated[str | None, Query(description="模型分类")] = None,
    state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TrainingTaskSummaryResponse]:
    """列出 segmentation 训练任务。"""

    require_project_access(
        principal_project_ids=principal.project_ids,
        project_id=project_id,
    )
    return list_training_tasks(
        session_factory=session_factory,
        project_id=project_id,
        task_type="segmentation",
        model_type=model_type,
        state=state,
        limit=limit,
    )


@segmentation_training_tasks_router.get(
    "/segmentation/training-tasks/{task_id}",
    response_model=TrainingTaskDetailResponse,
)
def get_segmentation_training_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> TrainingTaskDetailResponse:
    """获取 segmentation 训练任务详情。"""

    return get_training_task_detail(session_factory=session_factory, task_id=task_id)


@segmentation_training_tasks_router.post(
    "/segmentation/training-tasks/{task_id}/save",
    response_model=TrainingTaskDetailResponse,
)
def request_segmentation_training_save(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> TrainingTaskDetailResponse:
    """请求 segmentation 训练手动保存。"""

    return request_training_control(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        task_id=task_id,
        action="save",
    )


@segmentation_training_tasks_router.post(
    "/segmentation/training-tasks/{task_id}/pause",
    response_model=TrainingTaskDetailResponse,
)
def request_segmentation_training_pause(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> TrainingTaskDetailResponse:
    """请求 segmentation 训练暂停。"""

    return request_training_control(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        task_id=task_id,
        action="pause",
    )


@segmentation_training_tasks_router.post(
    "/segmentation/training-tasks/{task_id}/terminate",
    response_model=TrainingTaskDetailResponse,
)
def request_segmentation_training_terminate(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> TrainingTaskDetailResponse:
    """请求 segmentation 训练终止。"""

    return request_training_control(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        task_id=task_id,
        action="terminate",
    )


@segmentation_training_tasks_router.post(
    "/segmentation/training-tasks/{task_id}/resume",
    response_model=TrainingTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_segmentation_training_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> TrainingTaskSubmissionResponse:
    """继续 paused 的 segmentation 训练任务。"""

    return resume_training_task(
        session_factory=session_factory,
        queue_backend=queue_backend,
        task_id=task_id,
    )


@segmentation_training_tasks_router.delete(
    "/segmentation/training-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_segmentation_training_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> Response:
    """删除已停止的 segmentation 训练任务。"""

    delete_training_task(session_factory=session_factory, task_id=task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

