"""detection 训练任务查询 API。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory

from .responses import (
    DetectionTrainingTaskDetailResponse,
    DetectionTrainingTaskSummaryResponse,
    _build_detection_training_task_detail_response,
    _build_detection_training_task_summary_response,
)
from .services import (
    _matches_detection_training_filters,
    _require_visible_detection_training_task,
    _resolve_detection_training_task_kinds,
    _resolve_visible_project_ids,
)

detection_training_query_router = APIRouter()


@detection_training_query_router.get(
    "/detection/training-tasks",
    response_model=list[DetectionTrainingTaskSummaryResponse],
)
def list_detection_training_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    model_type: Annotated[str | None, Query(description="模型分类")] = None,
    state: Annotated[str | None, Query(description="任务状态")] = None,
    created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
    dataset_export_id: Annotated[str | None, Query(description="训练输入使用的 DatasetExport id")] = None,
    dataset_export_manifest_key: Annotated[str | None, Query(description="训练输入使用的导出 manifest object key")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[DetectionTrainingTaskSummaryResponse]:
    """按公开筛选条件列出 detection 训练任务。"""

    visible_project_ids = _resolve_visible_project_ids(principal=principal, project_id=project_id)
    task_kinds = _resolve_detection_training_task_kinds(model_type)
    service = SqlAlchemyTaskService(session_factory)
    matched_tasks = []
    for current_project_id in visible_project_ids:
        for task_kind in task_kinds:
            matched_tasks.extend(
                service.list_tasks(
                    TaskQueryFilters(
                        project_id=current_project_id,
                        task_kind=task_kind,
                        state=state,
                        created_by=created_by,
                        limit=limit,
                    )
                )
            )
    visible_tasks = [
        task
        for task in matched_tasks
        if _matches_detection_training_filters(
            task=task,
            dataset_export_id=dataset_export_id,
            dataset_export_manifest_key=dataset_export_manifest_key,
        )
    ]
    visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
    return [_build_detection_training_task_summary_response(task) for task in visible_tasks[:limit]]


@detection_training_query_router.get(
    "/detection/training-tasks/{task_id}",
    response_model=DetectionTrainingTaskDetailResponse,
)
def get_detection_training_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    include_events: Annotated[bool, Query(description="是否返回事件列表")] = False,
) -> DetectionTrainingTaskDetailResponse:
    """按任务 id 返回 detection 训练任务详情。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=include_events,
    )
    return _build_detection_training_task_detail_response(task_detail.task, tuple(task_detail.events))
