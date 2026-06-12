"""segmentation evaluation task REST 路由。"""

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
from backend.service.application.models.yolo_primary_segmentation_evaluation_task_service import (
    SEGMENTATION_EVALUATION_TASK_KIND,
    SqlAlchemyYoloPrimarySegmentationEvaluationTaskService,
    YoloPrimarySegmentationEvaluationTaskRequest,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


segmentation_evaluation_tasks_router = APIRouter(prefix="/models", tags=["models"])


class SegmentationEvaluationCreateBody(BaseModel):
    project_id: str = Field(description="所属 Project id")
    model_version_id: str = Field(description="待评估 ModelVersion id")
    dataset_export_id: str | None = Field(default=None, description="DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="导出 manifest key")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="score threshold")
    mask_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="mask threshold")
    save_result_package: bool = Field(default=True, description="是否输出结果包")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加选项")
    display_name: str = Field(default="", description="展示名称")


class SegmentationEvaluationSubmissionResponse(BaseModel):
    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_version_id: str
    model_version_id: str


class SegmentationEvaluationSummaryResponse(BaseModel):
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
    mask_map50: float | None = None
    mask_map50_95: float | None = None
    sample_count: int | None = None


class SegmentationEvaluationDetailResponse(SegmentationEvaluationSummaryResponse):
    metadata: dict[str, object] = Field(default_factory=dict)
    result: dict[str, object] = Field(default_factory=dict)


@segmentation_evaluation_tasks_router.post(
    "/segmentation/evaluation-tasks",
    response_model=SegmentationEvaluationSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_segmentation_evaluation_task(
    body: SegmentationEvaluationCreateBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read", "models:read", "tasks:write"))],
    sf: Annotated[SessionFactory, Depends(get_session_factory)],
    qb: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    ds: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> SegmentationEvaluationSubmissionResponse:
    """创建 segmentation 评估任务。"""
    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project")
    svc = SqlAlchemyYoloPrimarySegmentationEvaluationTaskService(session_factory=sf, dataset_storage=ds, queue_backend=qb)
    r = svc.submit_evaluation_task(
        YoloPrimarySegmentationEvaluationTaskRequest(
            project_id=body.project_id, model_version_id=body.model_version_id,
            dataset_export_id=body.dataset_export_id, dataset_export_manifest_key=body.dataset_export_manifest_key,
            score_threshold=body.score_threshold, mask_threshold=body.mask_threshold,
            save_result_package=body.save_result_package, extra_options=dict(body.extra_options)),
        created_by=principal.principal_id, display_name=body.display_name)
    return SegmentationEvaluationSubmissionResponse(
        task_id=r.task_id, status=r.status, queue_name=r.queue_name, queue_task_id=r.queue_task_id,
        dataset_export_id=r.dataset_export_id, dataset_version_id=r.dataset_version_id, model_version_id=r.model_version_id)


@segmentation_evaluation_tasks_router.get(
    "/segmentation/evaluation-tasks",
    response_model=list[SegmentationEvaluationSummaryResponse],
)
def list_segmentation_evaluation_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    sf: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str, Query(description="所属 Project id")],
    state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SegmentationEvaluationSummaryResponse]:
    """列出 segmentation 评估任务。"""
    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project")
    tasks = SqlAlchemyTaskService(sf).list_tasks(TaskQueryFilters(
        project_id=project_id, task_kind=SEGMENTATION_EVALUATION_TASK_KIND, state=state, limit=limit))
    return [_build_summary(t) for t in tasks]


@segmentation_evaluation_tasks_router.get(
    "/segmentation/evaluation-tasks/{task_id}",
    response_model=SegmentationEvaluationDetailResponse,
)
def get_segmentation_evaluation_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    sf: Annotated[SessionFactory, Depends(get_session_factory)],
) -> SegmentationEvaluationDetailResponse:
    """获取 segmentation 评估任务详情。"""
    detail = SqlAlchemyTaskService(sf).get_task(task_id)
    task = detail.task
    if task.task_kind != SEGMENTATION_EVALUATION_TASK_KIND:
        raise ResourceNotFoundError("找不到指定的评估任务")
    summary = _build_summary(task)
    return SegmentationEvaluationDetailResponse(
        **summary.model_dump(),
        metadata=dict(task.metadata) if task.metadata else {},
        result=dict(task.result) if task.result else {})


@segmentation_evaluation_tasks_router.delete(
    "/segmentation/evaluation-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_segmentation_evaluation_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    sf: Annotated[SessionFactory, Depends(get_session_factory)],
) -> Response:
    """删除已完成的 segmentation 评估任务。"""
    task_svc = SqlAlchemyTaskService(sf)
    detail = task_svc.get_task(task_id)
    if detail.task.task_kind != SEGMENTATION_EVALUATION_TASK_KIND:
        raise ResourceNotFoundError("找不到指定的评估任务")
    if detail.task.state in {"queued", "running"}:
        raise InvalidRequestError("当前评估任务仍在运行中，不能删除")
    task_svc.delete_task(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _build_summary(task) -> SegmentationEvaluationSummaryResponse:
    result = dict(task.result) if task.result else {}
    return SegmentationEvaluationSummaryResponse(
        task_id=task.task_id, display_name=task.display_name, project_id=task.project_id,
        state=task.state, created_at=task.created_at, started_at=task.started_at,
        finished_at=task.finished_at, error_message=task.error_message,
        map50=result.get("map50"), map50_95=result.get("map50_95"),
        mask_map50=result.get("mask_map50"), mask_map50_95=result.get("mask_map50_95"),
        sample_count=result.get("sample_count"))
