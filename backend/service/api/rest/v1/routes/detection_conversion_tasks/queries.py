"""detection conversion 查询路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.detection_conversion_tasks.responses import (
    DetectionConversionTaskDetailResponse,
    DetectionConversionTaskSummaryResponse,
    build_detection_conversion_task_detail,
    build_detection_conversion_task_summary,
)
from backend.service.api.rest.v1.routes.detection_conversion_tasks.services import (
    resolve_detection_conversion_task_kinds,
)
from backend.service.api.rest.v1.routes.detection_conversion_tasks.visibility import (
    matches_detection_conversion_filters,
    matches_detection_conversion_task_type,
    require_visible_detection_conversion_task,
    resolve_visible_project_ids,
)
from backend.service.api.rest.v1.routes.task_conversion.deletion import delete_conversion_task_outputs
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_conversion_query_router = APIRouter()


@detection_conversion_query_router.get(
    "/detection/conversion-tasks",
    response_model=list[DetectionConversionTaskSummaryResponse],
)
def list_detection_conversion_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    model_type: Annotated[str | None, Query(description="模型分类")] = None,
    state: Annotated[str | None, Query(description="任务状态")] = None,
    created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
    source_model_version_id: Annotated[str | None, Query(description="来源 ModelVersion id")] = None,
    target_format: Annotated[str | None, Query(description="目标 build 格式")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[DetectionConversionTaskSummaryResponse]:
    """按公开筛选条件列出 detection conversion 任务。"""

    visible_project_ids = resolve_visible_project_ids(principal=principal, project_id=project_id)
    task_kinds = resolve_detection_conversion_task_kinds(model_type)
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
        if matches_detection_conversion_task_type(task)
        and matches_detection_conversion_filters(
            task=task,
            source_model_version_id=source_model_version_id,
            target_format=target_format,
        )
    ]
    visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
    return [build_detection_conversion_task_summary(task) for task in visible_tasks[:limit]]


@detection_conversion_query_router.get(
    "/detection/conversion-tasks/{task_id}",
    response_model=DetectionConversionTaskDetailResponse,
)
def get_detection_conversion_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    include_events: Annotated[bool, Query(description="是否返回事件列表")] = False,
) -> DetectionConversionTaskDetailResponse:
    """按任务 id 返回 detection conversion 任务详情。"""

    task_detail = require_visible_detection_conversion_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=include_events,
    )
    return build_detection_conversion_task_detail(task_detail.task, tuple(task_detail.events))


@detection_conversion_query_router.delete(
    "/detection/conversion-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_detection_conversion_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:write", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> Response:
    """删除 detection conversion 任务运行数据和未被部署使用的输出。"""

    task_detail = require_visible_detection_conversion_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    delete_conversion_task_outputs(
        task=task_detail.task,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
