"""任务 REST 路由分组。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.tasks.task_service import (
	CreateTaskRequest,
	SqlAlchemyTaskService,
	TaskEventQueryFilters,
	TaskQueryFilters,
)
from backend.service.infrastructure.db.session import SessionFactory


tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreateRequestBody(BaseModel):
	"""描述公开创建任务接口的请求体。"""

	project_id: str = Field(description="所属 Project id")
	task_kind: str = Field(description="任务类型")
	display_name: str = Field(default="", description="展示名称")
	parent_task_id: str | None = Field(default=None, description="父任务 id")
	task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
	resource_profile_id: str | None = Field(default=None, description="资源画像 id")
	worker_pool: str | None = Field(default=None, description="目标 worker pool")
	metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class TaskEventResponse(BaseModel):
	"""描述任务事件响应。"""

	event_id: str = Field(description="事件 id")
	task_id: str = Field(description="所属任务 id")
	attempt_id: str | None = Field(default=None, description="关联尝试 id")
	event_type: str = Field(description="事件类型")
	created_at: str = Field(description="事件时间")
	message: str = Field(description="事件消息")
	payload: dict[str, object] = Field(default_factory=dict, description="事件负载")


class TaskSummaryResponse(BaseModel):
	"""描述任务摘要响应。"""

	task_id: str = Field(description="任务 id")
	task_kind: str = Field(description="任务类型")
	display_name: str = Field(description="展示名称")
	project_id: str = Field(description="所属 Project id")
	created_by: str | None = Field(default=None, description="提交主体 id")
	created_at: str = Field(description="创建时间")
	parent_task_id: str | None = Field(default=None, description="父任务 id")
	resource_profile_id: str | None = Field(default=None, description="资源画像 id")
	worker_pool: str | None = Field(default=None, description="worker pool 名称")
	state: str = Field(description="当前状态")
	current_attempt_no: int = Field(description="当前尝试序号")
	started_at: str | None = Field(default=None, description="开始时间")
	finished_at: str | None = Field(default=None, description="结束时间")
	progress: dict[str, object] = Field(default_factory=dict, description="进度快照")
	result: dict[str, object] = Field(default_factory=dict, description="结果摘要")
	error_message: str | None = Field(default=None, description="错误消息")
	metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class TaskDetailResponse(TaskSummaryResponse):
	"""描述任务详情响应。"""

	task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
	events: list[TaskEventResponse] = Field(default_factory=list, description="任务事件列表")


@tasks_router.post("", response_model=TaskDetailResponse, status_code=status.HTTP_201_CREATED)
def create_task(
	body: TaskCreateRequestBody,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> TaskDetailResponse:
	"""创建一条新的公开任务记录。"""

	if principal.project_ids and body.project_id not in principal.project_ids:
		raise PermissionDeniedError(
			"当前主体无权访问该 Project",
			details={"project_id": body.project_id},
		)

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

	return _build_task_detail_response(task_detail.task, task_detail.events)


@tasks_router.get("", response_model=list[TaskSummaryResponse])
def list_tasks(
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
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
	limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[TaskSummaryResponse]:
	"""按公开筛选字段列出任务摘要。"""

	project_ids = _resolve_visible_project_ids(principal=principal, project_id=project_id)
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
					limit=limit,
				)
			)
		)

	matched_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
	return [_build_task_summary_response(task) for task in matched_tasks[:limit]]


@tasks_router.get("/{task_id}", response_model=TaskDetailResponse)
def get_task_detail(
	task_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	include_events: Annotated[bool, Query(description="是否返回事件列表")] = True,
) -> TaskDetailResponse:
	"""按任务 id 返回任务详情。"""

	service = SqlAlchemyTaskService(session_factory)
	task_detail = service.get_task(task_id, include_events=include_events)
	_ensure_task_visible(principal=principal, task_project_id=task_detail.task.project_id, task_id=task_id)
	return _build_task_detail_response(task_detail.task, task_detail.events)


@tasks_router.get("/{task_id}/events", response_model=list[TaskEventResponse])
def list_task_events(
	task_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	event_type: Annotated[str | None, Query(description="事件类型")] = None,
	after_created_at: Annotated[str | None, Query(description="只返回晚于该时间的事件")] = None,
	limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[TaskEventResponse]:
	"""按任务 id 和筛选条件列出事件。"""

	service = SqlAlchemyTaskService(session_factory)
	task_detail = service.get_task(task_id)
	_ensure_task_visible(principal=principal, task_project_id=task_detail.task.project_id, task_id=task_id)
	events = service.list_task_events(
		TaskEventQueryFilters(
			task_id=task_id,
			event_type=event_type,
			after_created_at=after_created_at,
			limit=limit,
		)
	)
	return [_build_task_event_response(event) for event in events]


@tasks_router.post("/{task_id}/cancel", response_model=TaskDetailResponse)
def cancel_task(
	task_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> TaskDetailResponse:
	"""取消一条尚未结束的任务。"""

	service = SqlAlchemyTaskService(session_factory)
	task_detail = service.get_task(task_id)
	_ensure_task_visible(principal=principal, task_project_id=task_detail.task.project_id, task_id=task_id)
	cancelled_detail = service.cancel_task(task_id, cancelled_by=principal.principal_id)
	refreshed_detail = service.get_task(task_id, include_events=True)
	if cancelled_detail.task.state != "cancelled":
		raise InvalidRequestError("任务取消失败", details={"task_id": task_id})
	return _build_task_detail_response(refreshed_detail.task, refreshed_detail.events)


def _resolve_visible_project_ids(
	*,
	principal: AuthenticatedPrincipal,
	project_id: str | None,
) -> tuple[str, ...]:
	"""根据主体权限和查询条件解析可查询的 Project 范围。"""

	if project_id is not None:
		if principal.project_ids and project_id not in principal.project_ids:
			raise ResourceNotFoundError(
				"找不到指定的任务范围",
				details={"project_id": project_id},
			)
		return (project_id,)

	if principal.project_ids:
		return principal.project_ids

	raise InvalidRequestError("查询任务列表时必须提供 project_id")


def _ensure_task_visible(
	*,
	principal: AuthenticatedPrincipal,
	task_project_id: str,
	task_id: str,
) -> None:
	"""校验当前主体是否可以访问指定任务。"""

	if principal.project_ids and task_project_id not in principal.project_ids:
		raise ResourceNotFoundError(
			"找不到指定的任务",
			details={"task_id": task_id},
		)


def _build_task_summary_response(task: object) -> TaskSummaryResponse:
	"""把 TaskRecord 转成摘要响应。"""

	return TaskSummaryResponse(
		task_id=task.task_id,
		task_kind=task.task_kind,
		display_name=task.display_name,
		project_id=task.project_id,
		created_by=task.created_by,
		created_at=task.created_at,
		parent_task_id=task.parent_task_id,
		resource_profile_id=task.resource_profile_id,
		worker_pool=task.worker_pool,
		state=task.state,
		current_attempt_no=task.current_attempt_no,
		started_at=task.started_at,
		finished_at=task.finished_at,
		progress=dict(task.progress),
		result=dict(task.result),
		error_message=task.error_message,
		metadata=dict(task.metadata),
	)


def _build_task_detail_response(task: object, events: tuple[object, ...]) -> TaskDetailResponse:
	"""把任务和事件转换为详情响应。"""

	return TaskDetailResponse(
		**_build_task_summary_response(task).model_dump(),
		task_spec=dict(task.task_spec),
		events=[_build_task_event_response(event) for event in events],
	)


def _build_task_event_response(event: object) -> TaskEventResponse:
	"""把 TaskEvent 转成响应对象。"""

	return TaskEventResponse(
		event_id=event.event_id,
		task_id=event.task_id,
		attempt_id=event.attempt_id,
		event_type=event.event_type,
		created_at=event.created_at,
		message=event.message,
		payload=dict(event.payload),
	)