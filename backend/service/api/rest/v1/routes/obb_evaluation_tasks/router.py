"""OBB evaluation task REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.obb_evaluation_tasks.responses import (
    ObbEvaluationDetailResponse,
    ObbEvaluationSubmissionResponse,
    ObbEvaluationSummaryResponse,
)
from backend.service.api.rest.v1.routes.obb_evaluation_tasks.schemas import ObbEvaluationCreateBody
from backend.service.api.rest.v1.routes.obb_evaluation_tasks.services import (
    create_obb_evaluation_task_response,
    delete_obb_evaluation_task_response,
    get_obb_evaluation_task_response,
    list_obb_evaluation_task_responses,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


obb_evaluation_tasks_router = APIRouter(prefix="/models", tags=["models"])


@obb_evaluation_tasks_router.post(
    "/obb/evaluation-tasks",
    response_model=ObbEvaluationSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_obb_evaluation_task(
    body: ObbEvaluationCreateBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read", "models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ObbEvaluationSubmissionResponse:
    """创建 OBB 评估任务。"""

    return create_obb_evaluation_task_response(
        body=body,
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@obb_evaluation_tasks_router.get(
    "/obb/evaluation-tasks",
    response_model=list[ObbEvaluationSummaryResponse],
)
def list_obb_evaluation_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str, Query(description="所属 Project id")],
    state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ObbEvaluationSummaryResponse]:
    """列出 OBB 评估任务。"""

    return list_obb_evaluation_task_responses(
        principal=principal,
        session_factory=session_factory,
        project_id=project_id,
        state=state,
        limit=limit,
    )


@obb_evaluation_tasks_router.get(
    "/obb/evaluation-tasks/{task_id}",
    response_model=ObbEvaluationDetailResponse,
)
def get_obb_evaluation_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> ObbEvaluationDetailResponse:
    """获取 OBB 评估任务详情。"""

    return get_obb_evaluation_task_response(
        session_factory=session_factory,
        task_id=task_id,
    )


@obb_evaluation_tasks_router.delete(
    "/obb/evaluation-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_obb_evaluation_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> Response:
    """删除已完成的 OBB 评估任务。"""

    return delete_obb_evaluation_task_response(
        session_factory=session_factory,
        task_id=task_id,
    )
