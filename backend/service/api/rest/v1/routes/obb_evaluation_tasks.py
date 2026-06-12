"""obb evaluation task REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.models.obb_evaluation_task_service import (
    OBB_EVALUATION_TASK_KIND,
    ObbEvaluationTaskRequest,
    SqlAlchemyObbEvaluationTaskService,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


obb_evaluation_tasks_router = APIRouter(prefix="/models", tags=["models"])


class ObbEvaluationCreateBody(BaseModel):
    project_id: str = Field(description="所属 Project id")
    model_version_id: str = Field(description="待评估 ModelVersion id")
    dataset_export_id: str | None = Field(default=None, description="DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="导出 manifest key")
    score_threshold: float = Field(default=0.01, ge=0.0, le=1.0, description="置信度阈值")
    save_result_package: bool = Field(default=True, description="是否输出结果包")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加选项")
    display_name: str = Field(default="", description="展示名称")


class ObbEvaluationSubmissionResponse(BaseModel):
    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_version_id: str
    model_version_id: str


class ObbEvaluationSummaryResponse(BaseModel):
    task_id: str
    display_name: str
    project_id: str
    state: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None
    map50: float | None = None
    map50_95: float | None = None
    sample_count: int | None = None


class ObbEvaluationDetailResponse(ObbEvaluationSummaryResponse):
    metadata: dict[str, object] = Field(default_factory=dict)
    result: dict[str, object] = Field(default_factory=dict)


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
    """创建 obb 评估任务。"""

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project")
    service = SqlAlchemyObbEvaluationTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    submission = service.submit_evaluation_task(
        ObbEvaluationTaskRequest(
            project_id=body.project_id,
            model_version_id=body.model_version_id,
            dataset_export_id=body.dataset_export_id,
            dataset_export_manifest_key=body.dataset_export_manifest_key,
            score_threshold=body.score_threshold,
            save_result_package=body.save_result_package,
            extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
        display_name=body.display_name,
    )
    return ObbEvaluationSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        dataset_export_id=submission.dataset_export_id,
        dataset_version_id=submission.dataset_version_id,
        model_version_id=submission.model_version_id,
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
    """列出 obb 评估任务。"""

    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project")
    tasks = SqlAlchemyTaskService(session_factory).list_tasks(
        TaskQueryFilters(
            project_id=project_id,
            task_kind=OBB_EVALUATION_TASK_KIND,
            state=state,
            limit=limit,
        )
    )
    return [_build_summary(task) for task in tasks]


@obb_evaluation_tasks_router.get(
    "/obb/evaluation-tasks/{task_id}",
    response_model=ObbEvaluationDetailResponse,
)
def get_obb_evaluation_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> ObbEvaluationDetailResponse:
    """获取 obb 评估任务详情。"""

    detail = SqlAlchemyTaskService(session_factory).get_task(task_id)
    task = detail.task
    if task.task_kind != OBB_EVALUATION_TASK_KIND:
        raise ResourceNotFoundError("找不到指定的评估任务")
    summary = _build_summary(task)
    return ObbEvaluationDetailResponse(
        **summary.model_dump(),
        metadata=dict(task.metadata) if task.metadata else {},
        result=dict(task.result) if task.result else {},
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
    """删除已完成的 obb 评估任务。"""

    task_service = SqlAlchemyTaskService(session_factory)
    detail = task_service.get_task(task_id)
    if detail.task.task_kind != OBB_EVALUATION_TASK_KIND:
        raise ResourceNotFoundError("找不到指定的评估任务")
    if detail.task.state in {"queued", "running"}:
        raise InvalidRequestError("当前评估任务仍在运行中，不能删除")
    task_service.delete_task(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _build_summary(task) -> ObbEvaluationSummaryResponse:
    result = dict(task.result) if task.result else {}
    return ObbEvaluationSummaryResponse(
        task_id=task.task_id,
        display_name=task.display_name,
        project_id=task.project_id,
        state=task.state,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error_message=task.error_message,
        map50=result.get("map50"),
        map50_95=result.get("map50_95"),
        sample_count=result.get("sample_count"),
    )
