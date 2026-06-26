"""通用任务 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.rest.v1.pagination import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, paginate_sequence
from backend.service.api.rest.v1.routes.tasks.controls import cancel_task_response
from backend.service.api.rest.v1.routes.tasks.responses import (
    build_task_detail_response,
    build_task_event_response,
    build_task_query_detail_response,
    build_task_summary_response,
)
from backend.service.api.rest.v1.routes.tasks.schemas import (
    TaskCreateRequestBody,
    TaskDetailResponse,
    TaskEventResponse,
    TaskSummaryResponse,
)
from backend.service.api.rest.v1.routes.tasks.visibility import (
    ensure_project_writable,
    ensure_task_visible,
    resolve_visible_project_ids,
)
from backend.service.application.tasks.task_service import (
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskEventQueryFilters,
    TaskQueryFilters,
)
from backend.service.infrastructure.db.session import SessionFactory


tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


@tasks_router.post("", response_model=TaskDetailResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    body: TaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> TaskDetailResponse:
    """创建一条新的公开任务记录。"""

    ensure_project_writable(principal=principal, project_id=body.project_id)

    service = SqlAlchemyTaskService(session_factory)
    created_task = service.create_task(
        CreateTaskRequest(
            project_id=body.project_id,
            task_kind=body.task_kind,
            display_name=body.display_name,
            created_by=principal.principal_id,
            parent_task_id=body.parent_task_id,
            task_spec=dict(body.task_spec),
            resource_profile_id=body.resource_profile_id,
            worker_pool=body.worker_pool,
            metadata=dict(body.metadata),
        )
    )
    task_detail = service.get_task(created_task.task_id, include_events=True)

    return build_task_detail_response(task_detail.task, task_detail.events)


@tasks_router.get("", response_model=list[TaskSummaryResponse])
def list_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    response: Response,
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    task_kind: Annotated[str | None, Query(description="任务类型")] = None,
    state: Annotated[str | None, Query(description="任务状态")] = None,
    worker_pool: Annotated[str | None, Query(description="worker pool 名称")] = None,
    created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
    parent_task_id: Annotated[str | None, Query(description="父任务 id")] = None,
    dataset_id: Annotated[str | None, Query(description="task_spec.dataset_id")] = None,
    source_import_id: Annotated[
        str | None,
        Query(description="task_spec.dataset_import_id 或 metadata.source_import_id"),
    ] = None,
    offset: Annotated[int, Query(ge=0, description="结果偏移量")] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT, description="最大返回数量")] = DEFAULT_LIST_LIMIT,
) -> list[TaskSummaryResponse]:
    """按公开筛选字段列出任务摘要。"""

    project_ids = resolve_visible_project_ids(principal=principal, project_id=project_id)
    service = SqlAlchemyTaskService(session_factory)
    matched_tasks = []
    for current_project_id in project_ids:
        matched_tasks.extend(
            service.list_tasks(
                TaskQueryFilters(
                    project_id=current_project_id,
                    task_kind=task_kind,
                    state=state,
                    worker_pool=worker_pool,
                    created_by=created_by,
                    parent_task_id=parent_task_id,
                    dataset_id=dataset_id,
                    source_import_id=source_import_id,
                    limit=None,
                )
            )
        )

    matched_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
    paged_tasks = paginate_sequence(matched_tasks, response=response, offset=offset, limit=limit)
    return [build_task_summary_response(task) for task in paged_tasks]


@tasks_router.get("/{task_id}", response_model=TaskDetailResponse)
def get_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    include_events: Annotated[bool, Query(description="是否返回事件列表")] = False,
) -> TaskDetailResponse:
    """按任务 id 返回任务详情。

    默认返回轻量详情，不带 events；仅在 include_events=True 时返回历史事件列表。
    """

    service = SqlAlchemyTaskService(session_factory)
    task_detail = service.get_task(task_id, include_events=include_events)
    ensure_task_visible(principal=principal, task_project_id=task_detail.task.project_id, task_id=task_id)
    return build_task_query_detail_response(task_detail.task, task_detail.events)


@tasks_router.get("/{task_id}/events", response_model=list[TaskEventResponse])
def list_task_events(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    event_type: Annotated[str | None, Query(description="事件类型")] = None,
    after_created_at: Annotated[str | None, Query(description="只返回晚于该时间的事件")] = None,
    offset: Annotated[int, Query(ge=0, description="结果偏移量")] = 0,
    limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[TaskEventResponse]:
    """按任务 id 和筛选条件列出事件。"""

    service = SqlAlchemyTaskService(session_factory)
    task_detail = service.get_task(task_id)
    ensure_task_visible(principal=principal, task_project_id=task_detail.task.project_id, task_id=task_id)
    events = service.list_task_events(
        TaskEventQueryFilters(
            task_id=task_id,
            event_type=event_type,
            after_created_at=after_created_at,
            offset=offset,
            limit=limit,
        )
    )
    return [build_task_event_response(event) for event in events]


@tasks_router.post("/{task_id}/cancel", response_model=TaskDetailResponse)
def cancel_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> TaskDetailResponse:
    """取消一条尚未结束的任务。

    响应只返回本次取消动作新增的事件，不返回历史事件列表。
    """

    return cancel_task_response(task_id=task_id, principal=principal, session_factory=session_factory)
