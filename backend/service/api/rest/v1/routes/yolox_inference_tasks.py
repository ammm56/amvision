"""YOLOX inference tasks REST 路由。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.deployments.yolox_deployment_service import SqlAlchemyYoloXDeploymentService
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.models.yolox_inference_task_service import (
	YOLOX_INFERENCE_TASK_KIND,
	SqlAlchemyYoloXInferenceTaskService,
	YoloXInferenceTaskRequest,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


yolox_inference_tasks_router = APIRouter(prefix="/models", tags=["models"])


class YoloXInferenceTaskCreateRequestBody(BaseModel):
	"""描述 YOLOX 推理任务创建请求体。"""

	project_id: str = Field(description="所属 Project id")
	deployment_instance_id: str = Field(description="执行推理使用的 DeploymentInstance id")
	input_file_id: str | None = Field(default=None, description="平台内输入文件 id；当前为保留字段")
	input_uri: str | None = Field(default=None, description="输入图片 URI 或 object key")
	score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="推理阈值")
	save_result_image: bool = Field(default=False, description="是否输出预览图")
	extra_options: dict[str, object] = Field(default_factory=dict, description="附加推理选项")
	display_name: str = Field(default="", description="可选展示名称")


class YoloXInferenceTaskSubmissionResponse(BaseModel):
	"""描述 YOLOX 推理任务创建响应。"""

	task_id: str = Field(description="推理任务 id")
	status: str = Field(description="推理任务当前状态")
	queue_name: str = Field(description="提交到的队列名称")
	queue_task_id: str = Field(description="队列任务 id")
	deployment_instance_id: str = Field(description="DeploymentInstance id")
	input_uri: str = Field(description="归一化后的输入 URI")


class YoloXInferenceTaskSummaryResponse(BaseModel):
	"""描述 YOLOX 推理任务摘要响应。"""

	task_id: str = Field(description="推理任务 id")
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
	deployment_instance_id: str = Field(description="DeploymentInstance id")
	model_version_id: str | None = Field(default=None, description="解析到的 ModelVersion id")
	model_build_id: str | None = Field(default=None, description="解析到的 ModelBuild id")
	input_uri: str | None = Field(default=None, description="输入 URI")
	input_file_id: str | None = Field(default=None, description="平台内输入文件 id")
	score_threshold: float | None = Field(default=None, description="推理阈值")
	save_result_image: bool = Field(description="是否输出预览图")
	output_object_prefix: str | None = Field(default=None, description="输出目录前缀")
	result_object_key: str | None = Field(default=None, description="结果文件 object key")
	preview_image_object_key: str | None = Field(default=None, description="预览图 object key")
	detection_count: int | None = Field(default=None, description="检测框数量")
	latency_ms: float | None = Field(default=None, description="推理耗时")
	result_summary: dict[str, object] = Field(default_factory=dict, description="结果摘要")


class YoloXInferenceTaskDetailResponse(YoloXInferenceTaskSummaryResponse):
	"""描述 YOLOX 推理任务详情响应。"""

	task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
	events: list[dict[str, object]] = Field(default_factory=list, description="任务事件列表")


class YoloXInferenceTaskResultResponse(BaseModel):
	"""描述 YOLOX 推理结果读取响应。"""

	file_status: Literal["pending", "ready"] = Field(description="推理结果文件状态")
	task_state: str = Field(description="当前推理任务状态")
	object_key: str | None = Field(default=None, description="结果文件 object key")
	payload: dict[str, object] = Field(default_factory=dict, description="推理结果 JSON 内容")


@yolox_inference_tasks_router.post(
	"/yolox/inference-tasks",
	response_model=YoloXInferenceTaskSubmissionResponse,
	status_code=status.HTTP_202_ACCEPTED,
)
def create_yolox_inference_task(
	body: YoloXInferenceTaskCreateRequestBody,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> YoloXInferenceTaskSubmissionResponse:
	"""创建一个正式 YOLOX inference task。"""

	if principal.project_ids and body.project_id not in principal.project_ids:
		raise PermissionDeniedError(
			"当前主体无权访问该 Project",
			details={"project_id": body.project_id},
		)
	deployment_service = SqlAlchemyYoloXDeploymentService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
	)
	deployment_view = deployment_service.get_deployment_instance(body.deployment_instance_id)
	if deployment_view.project_id != body.project_id:
		raise InvalidRequestError(
			"deployment_instance_id 与 project_id 不匹配",
			details={
				"project_id": body.project_id,
				"deployment_project_id": deployment_view.project_id,
				"deployment_instance_id": body.deployment_instance_id,
			},
		)
	service = SqlAlchemyYoloXInferenceTaskService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		queue_backend=queue_backend,
	)
	submission = service.submit_inference_task(
		YoloXInferenceTaskRequest(
			project_id=body.project_id,
			deployment_instance_id=body.deployment_instance_id,
			input_file_id=body.input_file_id,
			input_uri=body.input_uri,
			score_threshold=body.score_threshold,
			save_result_image=body.save_result_image,
			extra_options=dict(body.extra_options),
		),
		created_by=principal.principal_id,
		display_name=body.display_name,
	)
	return YoloXInferenceTaskSubmissionResponse(
		task_id=submission.task_id,
		status=submission.status,
		queue_name=submission.queue_name,
		queue_task_id=submission.queue_task_id,
		deployment_instance_id=submission.deployment_instance_id,
		input_uri=submission.input_uri,
	)


@yolox_inference_tasks_router.get(
	"/yolox/inference-tasks",
	response_model=list[YoloXInferenceTaskSummaryResponse],
)
def list_yolox_inference_tasks(
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
	state: Annotated[str | None, Query(description="任务状态")] = None,
	created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
	deployment_instance_id: Annotated[str | None, Query(description="DeploymentInstance id")] = None,
	limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[YoloXInferenceTaskSummaryResponse]:
	"""按公开筛选条件列出 YOLOX 推理任务。"""

	project_ids = _resolve_visible_project_ids(principal=principal, project_id=project_id)
	service = SqlAlchemyTaskService(session_factory)
	matched_tasks = []
	for current_project_id in project_ids:
		matched_tasks.extend(
			service.list_tasks(
				TaskQueryFilters(
					project_id=current_project_id,
					task_kind=YOLOX_INFERENCE_TASK_KIND,
					state=state,
					created_by=created_by,
					limit=limit,
				)
			)
		)
	visible_tasks = [
		task
		for task in matched_tasks
		if _matches_inference_filters(
			task=task,
			deployment_instance_id=deployment_instance_id,
		)
	]
	visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
	return [_build_inference_task_summary_response(task) for task in visible_tasks[:limit]]


@yolox_inference_tasks_router.get(
	"/yolox/inference-tasks/{task_id}",
	response_model=YoloXInferenceTaskDetailResponse,
)
def get_yolox_inference_task_detail(
	task_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	include_events: Annotated[bool, Query(description="是否返回事件列表")] = True,
) -> YoloXInferenceTaskDetailResponse:
	"""按任务 id 返回 YOLOX 推理任务详情。"""

	task_detail = _require_visible_inference_task(
		principal=principal,
		task_id=task_id,
		session_factory=session_factory,
		include_events=include_events,
	)
	return _build_inference_task_detail_response(task_detail.task, tuple(task_detail.events))


@yolox_inference_tasks_router.get(
	"/yolox/inference-tasks/{task_id}/result",
	response_model=YoloXInferenceTaskResultResponse,
)
def get_yolox_inference_task_result(
	task_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> YoloXInferenceTaskResultResponse:
	"""按任务 id 返回当前推理结果。"""

	task_detail = _require_visible_inference_task(
		principal=principal,
		task_id=task_id,
		session_factory=session_factory,
		include_events=False,
	)
	result = dict(task_detail.task.result)
	object_key = _read_optional_str(result, "result_object_key")
	if object_key is None:
		if task_detail.task.state in {"queued", "running"}:
			return YoloXInferenceTaskResultResponse(
				file_status="pending",
				task_state=task_detail.task.state,
				object_key=None,
				payload={},
			)
		raise ResourceNotFoundError(
			"当前推理任务缺少结果文件",
			details={"task_id": task_id},
		)
	resolved_path = dataset_storage.resolve(object_key)
	if not resolved_path.is_file():
		if task_detail.task.state in {"queued", "running"}:
			return YoloXInferenceTaskResultResponse(
				file_status="pending",
				task_state=task_detail.task.state,
				object_key=object_key,
				payload={},
			)
		raise ResourceNotFoundError(
			"当前推理任务的结果文件不存在",
			details={"task_id": task_id, "object_key": object_key},
		)
	payload = dataset_storage.read_json(object_key)
	return YoloXInferenceTaskResultResponse(
		file_status="ready",
		task_state=task_detail.task.state,
		object_key=object_key,
		payload=dict(payload) if isinstance(payload, dict) else {},
	)


def _resolve_visible_project_ids(
	*,
	principal: AuthenticatedPrincipal,
	project_id: str | None,
) -> tuple[str, ...]:
	"""根据主体权限和查询条件解析可见 Project 范围。"""

	if project_id is not None:
		if principal.project_ids and project_id not in principal.project_ids:
			raise ResourceNotFoundError(
				"找不到指定的任务范围",
				details={"project_id": project_id},
			)
		return (project_id,)
	if principal.project_ids:
		return principal.project_ids
	raise InvalidRequestError("查询推理任务列表时必须提供 project_id")


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


def _require_visible_inference_task(
	*,
	principal: AuthenticatedPrincipal,
	task_id: str,
	session_factory: SessionFactory,
	include_events: bool,
):
	"""读取并校验当前主体可见的 YOLOX 推理任务。"""

	service = SqlAlchemyTaskService(session_factory)
	task_detail = service.get_task(task_id, include_events=include_events)
	_ensure_task_visible(
		principal=principal,
		task_id=task_id,
		task_project_id=task_detail.task.project_id,
	)
	if task_detail.task.task_kind != YOLOX_INFERENCE_TASK_KIND:
		raise ResourceNotFoundError(
			"找不到指定的 YOLOX 推理任务",
			details={"task_id": task_id},
		)
	return task_detail


def _matches_inference_filters(
	*,
	task: object,
	deployment_instance_id: str | None,
) -> bool:
	"""判断 YOLOX 推理任务是否满足额外筛选条件。"""

	if deployment_instance_id is None:
		return True
	task_spec = dict(task.task_spec)
	return task_spec.get("deployment_instance_id") == deployment_instance_id


def _build_inference_task_summary_response(task: object) -> YoloXInferenceTaskSummaryResponse:
	"""把 YOLOX 推理 TaskRecord 转成摘要响应。"""

	task_spec = dict(task.task_spec)
	result = dict(task.result)
	metadata = dict(task.metadata)
	detection_count = result.get("detection_count")
	latency_ms = result.get("latency_ms")
	return YoloXInferenceTaskSummaryResponse(
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
		deployment_instance_id=_require_str(task_spec, "deployment_instance_id"),
		model_version_id=_read_optional_str(result, "model_version_id")
		or _read_optional_str(metadata, "model_version_id"),
		model_build_id=_read_optional_str(result, "model_build_id")
		or _read_optional_str(metadata, "model_build_id"),
		input_uri=_read_optional_str(task_spec, "input_uri")
		or _read_optional_str(result, "input_uri"),
		input_file_id=_read_optional_str(task_spec, "input_file_id"),
		score_threshold=(
			float(task_spec["score_threshold"])
			if isinstance(task_spec.get("score_threshold"), int | float)
			else None
		),
		save_result_image=bool(task_spec.get("save_result_image") is True),
		output_object_prefix=_read_optional_str(result, "output_object_prefix"),
		result_object_key=_read_optional_str(result, "result_object_key"),
		preview_image_object_key=_read_optional_str(result, "preview_image_object_key"),
		detection_count=detection_count if isinstance(detection_count, int) else None,
		latency_ms=float(latency_ms) if isinstance(latency_ms, int | float) else None,
		result_summary=dict(result.get("result_summary")) if isinstance(result.get("result_summary"), dict) else {},
	)


def _build_inference_task_detail_response(
	task: object,
	events: tuple[object, ...],
) -> YoloXInferenceTaskDetailResponse:
	"""把 YOLOX 推理任务和事件转换为详情响应。"""

	summary = _build_inference_task_summary_response(task)
	return YoloXInferenceTaskDetailResponse(
		**summary.model_dump(),
		task_spec=dict(task.task_spec),
		events=[
			{
				"event_id": event.event_id,
				"task_id": event.task_id,
				"attempt_id": event.attempt_id,
				"event_type": event.event_type,
				"created_at": event.created_at,
				"message": event.message,
				"payload": dict(event.payload),
			}
			for event in events
		],
	)


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
	"""从字典中读取可选字符串字段。"""

	value = payload.get(key)
	if isinstance(value, str) and value.strip():
		return value.strip()
	return None


def _require_str(payload: dict[str, object], key: str) -> str:
	"""从字典中读取必填字符串。"""

	value = _read_optional_str(payload, key)
	if value is None:
		raise InvalidRequestError(
			"推理任务缺少必要字段",
			details={"field": key},
		)
	return value