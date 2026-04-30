"""模型 REST 路由分组。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.models.yolox_training_service import (
	SqlAlchemyYoloXTrainingTaskService,
	YOLOX_TRAINING_TASK_KIND,
	YoloXTrainingTaskRequest,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory


models_router = APIRouter(prefix="/models", tags=["models"])


class YoloXTrainingTaskCreateRequestBody(BaseModel):
	"""描述 YOLOX 训练任务创建请求体。"""

	project_id: str = Field(description="所属 Project id")
	dataset_export_id: str | None = Field(default=None, description="训练输入使用的 DatasetExport id")
	dataset_export_manifest_key: str | None = Field(default=None, description="训练输入使用的导出 manifest object key")
	recipe_id: str = Field(description="训练 recipe id")
	model_scale: str = Field(description="训练目标的模型 scale")
	output_model_name: str = Field(description="训练后登记的模型名")
	warm_start_model_version_id: str | None = Field(default=None, description="warm start 使用的 ModelVersion id")
	max_epochs: int | None = Field(default=None, description="最大训练轮数")
	batch_size: int | None = Field(default=None, description="batch size")
	input_size: tuple[int, int] | None = Field(default=None, description="训练输入尺寸")
	extra_options: dict[str, object] = Field(default_factory=dict, description="附加训练选项")
	display_name: str = Field(default="", description="可选的任务展示名称")


class YoloXTrainingTaskSubmissionResponse(BaseModel):
	"""描述 YOLOX 训练任务创建响应。"""

	task_id: str = Field(description="训练任务 id")
	status: str = Field(description="训练任务当前状态")
	queue_name: str = Field(description="提交到的队列名称")
	queue_task_id: str = Field(description="队列任务 id")
	dataset_export_id: str = Field(description="解析后的 DatasetExport id")
	dataset_export_manifest_key: str = Field(description="解析后的导出 manifest object key")
	dataset_version_id: str = Field(description="导出来源的 DatasetVersion id")
	format_id: str = Field(description="训练使用的数据集导出格式 id")


class YoloXTrainingTaskEventResponse(BaseModel):
	"""描述 YOLOX 训练任务事件响应。"""

	event_id: str = Field(description="事件 id")
	task_id: str = Field(description="所属任务 id")
	attempt_id: str | None = Field(default=None, description="关联尝试 id")
	event_type: str = Field(description="事件类型")
	created_at: str = Field(description="事件时间")
	message: str = Field(description="事件消息")
	payload: dict[str, object] = Field(default_factory=dict, description="事件负载")


class YoloXTrainingTaskSummaryResponse(BaseModel):
	"""描述 YOLOX 训练任务摘要响应。"""

	task_id: str = Field(description="训练任务 id")
	display_name: str = Field(description="展示名称")
	project_id: str = Field(description="所属 Project id")
	created_by: str | None = Field(default=None, description="提交主体 id")
	created_at: str = Field(description="创建时间")
	worker_pool: str | None = Field(default=None, description="worker pool 名称")
	state: str = Field(description="当前状态")
	current_attempt_no: int = Field(description="当前尝试序号")
	started_at: str | None = Field(default=None, description="开始时间")
	finished_at: str | None = Field(default=None, description="结束时间")
	progress: dict[str, object] = Field(default_factory=dict, description="进度快照")
	result: dict[str, object] = Field(default_factory=dict, description="结果快照")
	error_message: str | None = Field(default=None, description="错误消息")
	metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
	dataset_export_id: str | None = Field(default=None, description="训练输入使用的 DatasetExport id")
	dataset_export_manifest_key: str | None = Field(default=None, description="训练输入使用的导出 manifest object key")
	dataset_version_id: str | None = Field(default=None, description="训练输入使用的 DatasetVersion id")
	format_id: str | None = Field(default=None, description="训练输入导出格式 id")
	recipe_id: str | None = Field(default=None, description="训练 recipe id")
	model_scale: str | None = Field(default=None, description="训练目标的模型 scale")
	output_model_name: str | None = Field(default=None, description="训练输出模型名")
	checkpoint_object_key: str | None = Field(default=None, description="checkpoint 文件 object key")
	labels_object_key: str | None = Field(default=None, description="标签文件 object key")
	metrics_object_key: str | None = Field(default=None, description="训练指标文件 object key")
	summary_object_key: str | None = Field(default=None, description="训练摘要文件 object key")
	best_metric_name: str | None = Field(default=None, description="最佳指标名称")
	best_metric_value: float | None = Field(default=None, description="最佳指标值")
	training_summary: dict[str, object] = Field(default_factory=dict, description="训练摘要")


class YoloXTrainingTaskDetailResponse(YoloXTrainingTaskSummaryResponse):
	"""描述 YOLOX 训练任务详情响应。"""

	task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
	events: list[YoloXTrainingTaskEventResponse] = Field(default_factory=list, description="任务事件列表")


@models_router.post(
	"/yolox/training-tasks",
	response_model=YoloXTrainingTaskSubmissionResponse,
	status_code=status.HTTP_202_ACCEPTED,
)
def create_yolox_training_task(
	body: YoloXTrainingTaskCreateRequestBody,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read", "tasks:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> YoloXTrainingTaskSubmissionResponse:
	"""创建一个以 DatasetExport 为唯一输入边界的 YOLOX 训练任务。"""

	if principal.project_ids and body.project_id not in principal.project_ids:
		raise PermissionDeniedError(
			"当前主体无权访问该 Project",
			details={"project_id": body.project_id},
		)

	service = SqlAlchemyYoloXTrainingTaskService(
		session_factory=session_factory,
		queue_backend=queue_backend,
	)
	submission = service.submit_training_task(
		YoloXTrainingTaskRequest(
			project_id=body.project_id,
			dataset_export_id=body.dataset_export_id,
			dataset_export_manifest_key=body.dataset_export_manifest_key,
			recipe_id=body.recipe_id,
			model_scale=body.model_scale,
			output_model_name=body.output_model_name,
			warm_start_model_version_id=body.warm_start_model_version_id,
			max_epochs=body.max_epochs,
			batch_size=body.batch_size,
			input_size=body.input_size,
			extra_options=dict(body.extra_options),
		),
		created_by=principal.principal_id,
		display_name=body.display_name,
	)

	return YoloXTrainingTaskSubmissionResponse(
		task_id=submission.task_id,
		status=submission.status,
		queue_name=submission.queue_name,
		queue_task_id=submission.queue_task_id,
		dataset_export_id=submission.dataset_export_id,
		dataset_export_manifest_key=submission.dataset_export_manifest_key,
		dataset_version_id=submission.dataset_version_id,
		format_id=submission.format_id,
	)


@models_router.get(
	"/yolox/training-tasks",
	response_model=list[YoloXTrainingTaskSummaryResponse],
)
def list_yolox_training_tasks(
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
	state: Annotated[str | None, Query(description="任务状态")] = None,
	created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
	dataset_export_id: Annotated[str | None, Query(description="训练输入使用的 DatasetExport id")] = None,
	dataset_export_manifest_key: Annotated[
		str | None,
		Query(description="训练输入使用的导出 manifest object key"),
	] = None,
	limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[YoloXTrainingTaskSummaryResponse]:
	"""按公开筛选条件列出 YOLOX 训练任务。"""

	project_ids = _resolve_visible_project_ids(principal=principal, project_id=project_id)
	service = SqlAlchemyTaskService(session_factory)
	matched_tasks = []
	for current_project_id in project_ids:
		matched_tasks.extend(
			service.list_tasks(
				TaskQueryFilters(
					project_id=current_project_id,
					task_kind=YOLOX_TRAINING_TASK_KIND,
					state=state,
					created_by=created_by,
					limit=limit,
				)
			)
		)

	visible_tasks = [
		task
		for task in matched_tasks
		if _matches_yolox_training_filters(
			task=task,
			dataset_export_id=dataset_export_id,
			dataset_export_manifest_key=dataset_export_manifest_key,
		)
	]
	visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
	return [_build_yolox_training_task_summary_response(task) for task in visible_tasks[:limit]]


@models_router.get(
	"/yolox/training-tasks/{task_id}",
	response_model=YoloXTrainingTaskDetailResponse,
)
def get_yolox_training_task_detail(
	task_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	include_events: Annotated[bool, Query(description="是否返回事件列表")] = True,
) -> YoloXTrainingTaskDetailResponse:
	"""按任务 id 返回 YOLOX 训练任务详情。"""

	service = SqlAlchemyTaskService(session_factory)
	task_detail = service.get_task(task_id, include_events=include_events)
	_ensure_task_visible(
		principal=principal,
		task_id=task_id,
		task_project_id=task_detail.task.project_id,
	)
	if task_detail.task.task_kind != YOLOX_TRAINING_TASK_KIND:
		raise ResourceNotFoundError(
			"找不到指定的 YOLOX 训练任务",
			details={"task_id": task_id},
		)

	return _build_yolox_training_task_detail_response(task_detail.task, tuple(task_detail.events))


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

	raise InvalidRequestError("查询训练任务列表时必须提供 project_id")


def _ensure_task_visible(
	*,
	principal: AuthenticatedPrincipal,
	task_id: str,
	task_project_id: str,
) -> None:
	"""校验当前主体是否可以访问指定任务。"""

	if principal.project_ids and task_project_id not in principal.project_ids:
		raise ResourceNotFoundError(
			"找不到指定的任务",
			details={"task_id": task_id},
		)


def _matches_yolox_training_filters(
	*,
	task: object,
	dataset_export_id: str | None,
	dataset_export_manifest_key: str | None,
) -> bool:
	"""判断 YOLOX 训练任务是否满足额外筛选条件。"""

	task_spec = dict(task.task_spec)
	if dataset_export_id is not None and task_spec.get("dataset_export_id") != dataset_export_id:
		return False
	if (
		dataset_export_manifest_key is not None
		and task_spec.get("dataset_export_manifest_key") != dataset_export_manifest_key
	):
		return False

	return True


def _build_yolox_training_task_summary_response(task: object) -> YoloXTrainingTaskSummaryResponse:
	"""把 YOLOX 训练 TaskRecord 转成摘要响应。"""

	task_spec = dict(task.task_spec)
	result = dict(task.result)
	metadata = dict(task.metadata)
	training_summary = result.get("summary")
	best_metric_value = result.get("best_metric_value")
	return YoloXTrainingTaskSummaryResponse(
		task_id=task.task_id,
		display_name=task.display_name,
		project_id=task.project_id,
		created_by=task.created_by,
		created_at=task.created_at,
		worker_pool=task.worker_pool,
		state=task.state,
		current_attempt_no=task.current_attempt_no,
		started_at=task.started_at,
		finished_at=task.finished_at,
		progress=dict(task.progress),
		result=result,
		error_message=task.error_message,
		metadata=metadata,
		dataset_export_id=_read_optional_str(task_spec, "dataset_export_id"),
		dataset_export_manifest_key=_read_optional_str(task_spec, "dataset_export_manifest_key"),
		dataset_version_id=_read_optional_str(result, "dataset_version_id")
		or _read_optional_str(metadata, "dataset_version_id"),
		format_id=_read_optional_str(result, "format_id")
		or _read_optional_str(metadata, "format_id"),
		recipe_id=_read_optional_str(task_spec, "recipe_id"),
		model_scale=_read_optional_str(task_spec, "model_scale"),
		output_model_name=_read_optional_str(task_spec, "output_model_name"),
		checkpoint_object_key=_read_optional_str(result, "checkpoint_object_key"),
		labels_object_key=_read_optional_str(result, "labels_object_key"),
		metrics_object_key=_read_optional_str(result, "metrics_object_key"),
		summary_object_key=_read_optional_str(result, "summary_object_key"),
		best_metric_name=_read_optional_str(result, "best_metric_name"),
		best_metric_value=(
			float(best_metric_value)
			if isinstance(best_metric_value, int | float)
			else None
		),
		training_summary=dict(training_summary) if isinstance(training_summary, dict) else {},
	)


def _build_yolox_training_task_detail_response(
	task: object,
	events: tuple[object, ...],
) -> YoloXTrainingTaskDetailResponse:
	"""把 YOLOX 训练任务和事件转换为详情响应。"""

	return YoloXTrainingTaskDetailResponse(
		**_build_yolox_training_task_summary_response(task).model_dump(),
		task_spec=dict(task.task_spec),
		events=[_build_yolox_training_task_event_response(event) for event in events],
	)


def _build_yolox_training_task_event_response(event: object) -> YoloXTrainingTaskEventResponse:
	"""把 TaskEvent 转成 YOLOX 训练任务事件响应。"""

	return YoloXTrainingTaskEventResponse(
		event_id=event.event_id,
		task_id=event.task_id,
		attempt_id=event.attempt_id,
		event_type=event.event_type,
		created_at=event.created_at,
		message=event.message,
		payload=dict(event.payload),
	)


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
	"""从字典中读取可选字符串字段。"""

	value = payload.get(key)
	if isinstance(value, str) and value.strip():
		return value
	return None