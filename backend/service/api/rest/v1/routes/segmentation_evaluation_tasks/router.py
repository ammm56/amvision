"""segmentation evaluation task REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.segmentation_evaluation_tasks.responses import (
    SegmentationEvaluationDetailResponse,
    SegmentationEvaluationSubmissionResponse,
    SegmentationEvaluationSummaryResponse,
)
from backend.service.api.rest.v1.routes.segmentation_evaluation_tasks.schemas import (
    SegmentationEvaluationCreateBody,
)
from backend.service.api.rest.v1.routes.segmentation_evaluation_tasks.services import (
    create_segmentation_evaluation_task_response,
    delete_segmentation_evaluation_task_response,
    get_segmentation_evaluation_task_response,
    list_segmentation_evaluation_task_responses,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


segmentation_evaluation_tasks_router = APIRouter(prefix="/models", tags=["models"])


@segmentation_evaluation_tasks_router.post(
    "/segmentation/evaluation-tasks",
    response_model=SegmentationEvaluationSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_segmentation_evaluation_task(
    body: SegmentationEvaluationCreateBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read", "models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> SegmentationEvaluationSubmissionResponse:
    """创建 segmentation 评估任务。"""

    return create_segmentation_evaluation_task_response(
        body=body,
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@segmentation_evaluation_tasks_router.get(
    "/segmentation/evaluation-tasks",
    response_model=list[SegmentationEvaluationSummaryResponse],
)
def list_segmentation_evaluation_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str, Query(description="所属 Project id")],
    state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SegmentationEvaluationSummaryResponse]:
    """列出 segmentation 评估任务。"""

    return list_segmentation_evaluation_task_responses(
        principal=principal,
        session_factory=session_factory,
        project_id=project_id,
        state=state,
        limit=limit,
    )


@segmentation_evaluation_tasks_router.get(
    "/segmentation/evaluation-tasks/{task_id}",
    response_model=SegmentationEvaluationDetailResponse,
)
def get_segmentation_evaluation_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> SegmentationEvaluationDetailResponse:
    """获取 segmentation 评估任务详情。"""

    return get_segmentation_evaluation_task_response(
        session_factory=session_factory,
        task_id=task_id,
    )


@segmentation_evaluation_tasks_router.delete(
    "/segmentation/evaluation-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_segmentation_evaluation_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> Response:
    """删除已完成的 segmentation 评估任务。"""

    return delete_segmentation_evaluation_task_response(
        session_factory=session_factory,
        task_id=task_id,
    )
