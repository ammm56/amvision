"""classification evaluation task REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import PermissionDeniedError
from backend.service.application.models.evaluation.yolo_primary_classification_evaluation_task_service import (
    CLASSIFICATION_EVALUATION_TASK_KIND,
    SqlAlchemyYoloPrimaryClassificationEvaluationTaskService,
    YoloPrimaryClassificationEvaluationTaskRequest,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


classification_evaluation_tasks_router = APIRouter(prefix="/models", tags=["models"])


class ClassificationEvaluationCreateBody(BaseModel):
    project_id: str = Field(description="所属 Project id")
    model_version_id: str = Field(description="待评估 ModelVersion id")
    dataset_export_id: str | None = Field(default=None, description="DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="导出 manifest key")
    top_k: int = Field(default=5, ge=1, le=100, description="返回 top-k 分类结果数量")
    save_result_package: bool = Field(default=True, description="是否输出结果包")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加选项")
    display_name: str = Field(default="", description="展示名称")


class ClassificationEvaluationSubmissionResponse(BaseModel):
    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_version_id: str
    model_version_id: str


class ClassificationEvaluationSummaryResponse(BaseModel):
    task_id: str
    display_name: str
    project_id: str
    state: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None
    top1_accuracy: float | None = None
    top5_accuracy: float | None = None
    sample_count: int | None = None


class ClassificationEvaluationDetailResponse(ClassificationEvaluationSummaryResponse):
    metadata: dict[str, object] = Field(default_factory=dict)
    result: dict[str, object] = Field(default_factory=dict)


@classification_evaluation_tasks_router.post(
    "/classification/evaluation-tasks",
    response_model=ClassificationEvaluationSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_classification_evaluation_task(
    body: ClassificationEvaluationCreateBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read", "models:read", "tasks:write"))],
    sf: Annotated[SessionFactory, Depends(get_session_factory)],
    qb: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    ds: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ClassificationEvaluationSubmissionResponse:
    """创建 classification 评估任务。"""
    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project")
    svc = SqlAlchemyYoloPrimaryClassificationEvaluationTaskService(session_factory=sf, dataset_storage=ds, queue_backend=qb)
    r = svc.submit_evaluation_task(
        YoloPrimaryClassificationEvaluationTaskRequest(
            project_id=body.project_id, model_version_id=body.model_version_id,
            dataset_export_id=body.dataset_export_id, dataset_export_manifest_key=body.dataset_export_manifest_key,
            top_k=body.top_k, save_result_package=body.save_result_package,
            extra_options=dict(body.extra_options)),
        created_by=principal.principal_id, display_name=body.display_name)
    return ClassificationEvaluationSubmissionResponse(
        task_id=r.task_id, status=r.status, queue_name=r.queue_name, queue_task_id=r.queue_task_id,
        dataset_export_id=r.dataset_export_id, dataset_version_id=r.dataset_version_id, model_version_id=r.model_version_id)


@classification_evaluation_tasks_router.get(
    "/classification/evaluation-tasks",
    response_model=list[ClassificationEvaluationSummaryResponse],
)
def list_classification_evaluation_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    sf: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str, Query(description="所属 Project id")],
    state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ClassificationEvaluationSummaryResponse]:
    """列出 classification 评估任务。"""
    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project")
    task_svc = SqlAlchemyTaskService(sf)
    tasks = task_svc.list_tasks(TaskQueryFilters(project_id=project_id, task_kind=CLASSIFICATION_EVALUATION_TASK_KIND, state=state, limit=limit))
    return [_build_summary(t) for t in tasks]


@classification_evaluation_tasks_router.get(
    "/classification/evaluation-tasks/{task_id}",
    response_model=ClassificationEvaluationDetailResponse,
)
def get_classification_evaluation_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    sf: Annotated[SessionFactory, Depends(get_session_factory)],
) -> ClassificationEvaluationDetailResponse:
    """获取 classification 评估任务详情。"""
    detail = SqlAlchemyTaskService(sf).get_task(task_id)
    task = detail.task
    if task.task_kind != CLASSIFICATION_EVALUATION_TASK_KIND:
        from backend.service.application.errors import ResourceNotFoundError
        raise ResourceNotFoundError("找不到指定的评估任务")
    summary = _build_summary(task)
    result = dict(task.result) if task.result else {}
    return ClassificationEvaluationDetailResponse(
        **summary.model_dump(), metadata=dict(task.metadata) if task.metadata else {}, result=result)


@classification_evaluation_tasks_router.delete(
    "/classification/evaluation-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_classification_evaluation_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    sf: Annotated[SessionFactory, Depends(get_session_factory)],
) -> Response:
    """删除已完成的 classification 评估任务。"""
    task_svc = SqlAlchemyTaskService(sf)
    detail = task_svc.get_task(task_id)
    if detail.task.task_kind != CLASSIFICATION_EVALUATION_TASK_KIND:
        from backend.service.application.errors import ResourceNotFoundError
        raise ResourceNotFoundError("找不到指定的评估任务")
    if detail.task.state in {"queued", "running"}:
        from backend.service.application.errors import InvalidRequestError
        raise InvalidRequestError("当前评估任务仍在运行中，不能删除")
    task_svc.delete_task(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _build_summary(task) -> ClassificationEvaluationSummaryResponse:
    result = dict(task.result) if task.result else {}
    return ClassificationEvaluationSummaryResponse(
        task_id=task.task_id, display_name=task.display_name, project_id=task.project_id,
        state=task.state, created_at=task.created_at, started_at=task.started_at,
        finished_at=task.finished_at, error_message=task.error_message,
        top1_accuracy=result.get("top1_accuracy"), top5_accuracy=result.get("top5_accuracy"),
        sample_count=result.get("sample_count"))
