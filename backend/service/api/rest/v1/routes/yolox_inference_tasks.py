"""YOLOX inference tasks REST 路由。"""

from __future__ import annotations

import json
from uuid import uuid4

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.deps.yolox_deployment_process_supervisor import (
	get_yolox_async_deployment_process_supervisor,
	get_yolox_sync_deployment_process_supervisor,
)
from backend.service.application.deployments.yolox_deployment_service import SqlAlchemyYoloXDeploymentService
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.models.yolox_inference_payloads import (
	YoloXInferenceInputSource,
	build_yolox_inference_payload,
	normalize_yolox_inference_input,
	serialize_yolox_inference_payload,
)
from backend.service.application.models.yolox_inference_task_service import (
	YOLOX_INFERENCE_TASK_KIND,
	SqlAlchemyYoloXInferenceTaskService,
	YoloXInferenceTaskRequest,
	run_yolox_inference_task,
)
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
	YoloXDeploymentProcessSupervisor,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


yolox_inference_tasks_router = APIRouter(prefix="/models", tags=["models"])


_DEFAULT_INFERENCE_SCORE_THRESHOLD = 0.3


class YoloXInferenceTaskCreateRequestBody(BaseModel):
	"""描述 YOLOX 推理任务创建请求体。"""

	project_id: str = Field(description="所属 Project id")
	deployment_instance_id: str = Field(description="执行推理使用的 DeploymentInstance id")
	input_file_id: str | None = Field(default=None, description="平台内输入文件 id；当前为保留字段")
	input_uri: str | None = Field(default=None, description="输入图片 URI 或 object key")
	image_base64: str | None = Field(default=None, description="直接提交的 base64 图片内容")
	score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="推理阈值")
	save_result_image: bool = Field(default=False, description="是否输出预览图")
	return_preview_image_base64: bool = Field(default=False, description="是否在响应中直接返回预览图 base64")
	extra_options: dict[str, object] = Field(default_factory=dict, description="附加推理选项")
	display_name: str = Field(default="", description="可选展示名称")


class YoloXDirectInferenceRequestBody(BaseModel):
	"""描述同步直返推理请求体。"""

	input_file_id: str | None = Field(default=None, description="平台内输入文件 id；当前为保留字段")
	input_uri: str | None = Field(default=None, description="输入图片 URI 或 object key")
	image_base64: str | None = Field(default=None, description="直接提交的 base64 图片内容")
	score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="推理阈值")
	save_result_image: bool = Field(default=False, description="是否输出预览图")
	return_preview_image_base64: bool = Field(default=False, description="是否在响应中直接返回预览图 base64")
	extra_options: dict[str, object] = Field(default_factory=dict, description="附加推理选项")


class YoloXInferenceTaskSubmissionResponse(BaseModel):
	"""描述 YOLOX 推理任务创建响应。"""

	task_id: str = Field(description="推理任务 id")
	status: str = Field(description="推理任务当前状态")
	queue_name: str = Field(description="提交到的队列名称")
	queue_task_id: str = Field(description="队列任务 id")
	deployment_instance_id: str = Field(description="DeploymentInstance id")
	input_uri: str = Field(description="归一化后的输入 URI")
	input_source_kind: str = Field(description="输入来源类型")


class YoloXInferenceRuntimeTensorSpecResponse(BaseModel):
	"""描述推理运行时张量规格。"""

	name: str = Field(description="张量名称")
	shape: tuple[int, ...] = Field(description="张量形状")
	dtype: str = Field(description="张量数据类型")


class YoloXInferenceRuntimeSessionInfoResponse(BaseModel):
	"""描述推理运行时会话信息。"""

	backend_name: str = Field(description="运行时 backend 名称")
	model_uri: str = Field(description="当前加载模型 URI")
	device_name: str = Field(description="当前执行 device 名称")
	input_spec: YoloXInferenceRuntimeTensorSpecResponse = Field(description="输入张量规格")
	output_spec: YoloXInferenceRuntimeTensorSpecResponse = Field(description="输出张量规格")
	metadata: dict[str, object] = Field(default_factory=dict, description="附加运行时元数据")


class YoloXInferenceDetectionResponse(BaseModel):
	"""描述单条推理 detection 结果。"""

	bbox_xyxy: tuple[float, float, float, float] = Field(description="检测框坐标，格式为 xyxy")
	score: float = Field(description="检测得分")
	class_id: int = Field(description="类别 id")
	class_name: str | None = Field(default=None, description="类别名")


class YoloXInferencePayloadResponse(BaseModel):
	"""描述同步直返与异步结果共用的推理结果载荷。"""

	request_id: str = Field(description="统一请求 id")
	inference_task_id: str | None = Field(default=None, description="异步推理任务 id；同步场景为空")
	deployment_instance_id: str = Field(description="DeploymentInstance id")
	instance_id: str | None = Field(default=None, description="实际执行推理的实例 id")
	model_version_id: str = Field(description="推理使用的 ModelVersion id")
	model_build_id: str | None = Field(default=None, description="推理使用的 ModelBuild id")
	input_uri: str = Field(description="归一化后的输入 URI")
	input_source_kind: str = Field(description="输入来源类型")
	input_file_id: str | None = Field(default=None, description="平台内输入文件 id；当前固定为空")
	score_threshold: float = Field(description="本次推理阈值")
	save_result_image: bool = Field(description="是否保存预览图")
	return_preview_image_base64: bool = Field(description="是否直接返回预览图 base64")
	image_width: int = Field(description="输入图片宽度")
	image_height: int = Field(description="输入图片高度")
	detection_count: int = Field(description="检测框数量")
	latency_ms: float | None = Field(default=None, description="推理耗时，单位毫秒")
	labels: list[str] = Field(default_factory=list, description="类别列表")
	detections: list[YoloXInferenceDetectionResponse] = Field(default_factory=list, description="检测结果列表")
	runtime_session_info: YoloXInferenceRuntimeSessionInfoResponse = Field(description="运行时会话信息")
	preview_image_uri: str | None = Field(default=None, description="预览图 URI 或 object key")
	preview_image_base64: str | None = Field(default=None, description="预览图 base64 内容")
	result_object_key: str | None = Field(default=None, description="结果文件 object key")


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
	instance_id: str | None = Field(default=None, description="实际执行推理的实例 id")
	model_version_id: str | None = Field(default=None, description="解析到的 ModelVersion id")
	model_build_id: str | None = Field(default=None, description="解析到的 ModelBuild id")
	input_uri: str | None = Field(default=None, description="输入 URI")
	input_source_kind: str | None = Field(default=None, description="输入来源类型")
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
async def create_yolox_inference_task(
	request: Request,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	deployment_process_supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_async_deployment_process_supervisor)],
) -> YoloXInferenceTaskSubmissionResponse:
	"""创建一个正式 YOLOX inference task。"""

	body, input_source = await _read_yolox_inference_task_create_request(request)

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
	deployment_process_supervisor.ensure_deployment(
		deployment_service.resolve_process_config(body.deployment_instance_id)
	)
	_require_running_deployment_process(
		deployment_process_supervisor=deployment_process_supervisor,
		process_config=deployment_service.resolve_process_config(body.deployment_instance_id),
		runtime_mode="async",
	)
	normalized_input = normalize_yolox_inference_input(
		dataset_storage=dataset_storage,
		request_id=_resolve_http_request_id(request, prefix="inference-task-submit"),
		source=input_source,
	)
	service = SqlAlchemyYoloXInferenceTaskService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		queue_backend=queue_backend,
		deployment_process_supervisor=deployment_process_supervisor,
	)
	submission = service.submit_inference_task(
		YoloXInferenceTaskRequest(
			project_id=body.project_id,
			deployment_instance_id=body.deployment_instance_id,
			input_file_id=body.input_file_id,
			input_uri=normalized_input.input_uri,
			input_source_kind=normalized_input.input_source_kind,
			score_threshold=body.score_threshold,
			save_result_image=body.save_result_image,
			return_preview_image_base64=body.return_preview_image_base64,
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
		input_source_kind=normalized_input.input_source_kind,
	)


@yolox_inference_tasks_router.post(
	"/yolox/deployment-instances/{deployment_instance_id}/infer",
	response_model=YoloXInferencePayloadResponse,
)
async def infer_yolox_deployment_instance(
	deployment_instance_id: str,
	request: Request,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	deployment_process_supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_sync_deployment_process_supervisor)],
) -> YoloXInferencePayloadResponse:
	"""直接执行一次同步 YOLOX 推理并返回结果。"""

	body, input_source = await _read_yolox_direct_inference_request(request)
	deployment_service = SqlAlchemyYoloXDeploymentService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
	)
	deployment_view = deployment_service.get_deployment_instance(deployment_instance_id)
	_ensure_visible_deployment(principal=principal, deployment_project_id=deployment_view.project_id, deployment_instance_id=deployment_instance_id)
	process_config = deployment_service.resolve_process_config(deployment_instance_id)
	deployment_process_supervisor.ensure_deployment(process_config)
	_require_running_deployment_process(
		deployment_process_supervisor=deployment_process_supervisor,
		process_config=process_config,
		runtime_mode="sync",
	)
	request_id = _resolve_http_request_id(request, prefix="direct-inference")
	normalized_input = normalize_yolox_inference_input(
		dataset_storage=dataset_storage,
		request_id=request_id,
		source=input_source,
	)
	execution_result = run_yolox_inference_task(
		deployment_process_supervisor=deployment_process_supervisor,
		process_config=process_config,
		input_uri=normalized_input.input_uri,
		score_threshold=_resolve_requested_score_threshold(body.score_threshold),
		save_result_image=body.save_result_image,
		return_preview_image_base64=body.return_preview_image_base64,
		extra_options=dict(body.extra_options),
	)
	output_prefix = f"runtime/direct-inference/{request_id}"
	preview_image_uri = None
	if body.save_result_image and execution_result.preview_image_bytes is not None:
		preview_image_uri = f"{output_prefix}/preview.jpg"
		dataset_storage.write_bytes(preview_image_uri, execution_result.preview_image_bytes)
	result_object_key = f"{output_prefix}/raw-result.json"
	payload = build_yolox_inference_payload(
		request_id=request_id,
		inference_task_id=None,
		deployment_instance_id=deployment_instance_id,
		instance_id=execution_result.instance_id,
		runtime_target=process_config.runtime_target,
		normalized_input=normalized_input,
		score_threshold=_resolve_requested_score_threshold(body.score_threshold),
		save_result_image=body.save_result_image,
		return_preview_image_base64=body.return_preview_image_base64,
		execution_result=execution_result,
		preview_image_uri=preview_image_uri,
		result_object_key=result_object_key,
	)
	serialized_payload = serialize_yolox_inference_payload(payload)
	dataset_storage.write_json(result_object_key, serialized_payload)
	return YoloXInferencePayloadResponse.model_validate(serialized_payload)


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


def _ensure_visible_deployment(
	*,
	principal: AuthenticatedPrincipal,
	deployment_project_id: str,
	deployment_instance_id: str,
) -> None:
	"""校验当前主体是否可以访问指定 DeploymentInstance。"""

	if principal.project_ids and deployment_project_id not in principal.project_ids:
		raise ResourceNotFoundError(
			"找不到指定的 DeploymentInstance",
			details={"deployment_instance_id": deployment_instance_id},
		)


def _require_running_deployment_process(
	*,
	deployment_process_supervisor: YoloXDeploymentProcessSupervisor,
	process_config,
	runtime_mode: str,
) -> None:
	"""校验目标 deployment 子进程已经处于 running 状态。"""

	status = deployment_process_supervisor.get_status(process_config)
	if status.process_state == "running":
		return
	raise InvalidRequestError(
		"当前 deployment 进程尚未启动，请先调用 start 或 warmup 接口",
		details={
			"deployment_instance_id": process_config.deployment_instance_id,
			"runtime_mode": runtime_mode,
			"process_state": status.process_state,
			"required_actions": [f"{runtime_mode}/start", f"{runtime_mode}/warmup"],
		},
	)


async def _read_yolox_inference_task_create_request(
	request: Request,
) -> tuple[YoloXInferenceTaskCreateRequestBody, YoloXInferenceInputSource]:
	"""读取正式 inference task 的 JSON 或 multipart 请求。"""

	payload, input_source = await _read_yolox_inference_request_payload(request)
	try:
		return YoloXInferenceTaskCreateRequestBody.model_validate(payload), input_source
	except Exception as error:
		raise InvalidRequestError(
			"推理任务创建请求不合法",
			details={"error": str(error)},
		) from error


async def _read_yolox_direct_inference_request(
	request: Request,
) -> tuple[YoloXDirectInferenceRequestBody, YoloXInferenceInputSource]:
	"""读取同步直返推理的 JSON 或 multipart 请求。"""

	payload, input_source = await _read_yolox_inference_request_payload(request)
	payload.pop("project_id", None)
	payload.pop("deployment_instance_id", None)
	payload.pop("display_name", None)
	try:
		return YoloXDirectInferenceRequestBody.model_validate(payload), input_source
	except Exception as error:
		raise InvalidRequestError(
			"同步推理请求不合法",
			details={"error": str(error)},
		) from error


async def _read_yolox_inference_request_payload(
	request: Request,
) -> tuple[dict[str, object], YoloXInferenceInputSource]:
	"""按 content-type 读取推理请求，并保留 one-of 输入源信息。"""

	content_type = (request.headers.get("content-type") or "").lower()
	if content_type.startswith("multipart/form-data"):
		form = await request.form()
		upload = form.get("input_image")
		upload_bytes = None
		upload_filename = None
		upload_content_type = None
		if upload is not None:
			if not hasattr(upload, "read"):
				raise InvalidRequestError("input_image 必须是有效的上传文件")
			upload_bytes = await upload.read()
			upload_filename = getattr(upload, "filename", None)
			upload_content_type = getattr(upload, "content_type", None)
		payload = {
			"project_id": _read_optional_form_str(form, "project_id"),
			"deployment_instance_id": _read_optional_form_str(form, "deployment_instance_id"),
			"input_file_id": _read_optional_form_str(form, "input_file_id"),
			"input_uri": _read_optional_form_str(form, "input_uri"),
			"image_base64": _read_optional_form_str(form, "image_base64"),
			"score_threshold": _parse_optional_form_float(form.get("score_threshold"), field_name="score_threshold"),
			"save_result_image": _parse_optional_form_bool(form.get("save_result_image"), field_name="save_result_image", default=False),
			"return_preview_image_base64": _parse_optional_form_bool(form.get("return_preview_image_base64"), field_name="return_preview_image_base64", default=False),
			"extra_options": _parse_optional_form_json_dict(form.get("extra_options"), field_name="extra_options"),
			"display_name": _read_optional_form_str(form, "display_name") or "",
		}
		return payload, YoloXInferenceInputSource(
			input_uri=payload.get("input_uri") if isinstance(payload.get("input_uri"), str) else None,
			image_base64=payload.get("image_base64") if isinstance(payload.get("image_base64"), str) else None,
			upload_bytes=upload_bytes,
			upload_filename=upload_filename,
			upload_content_type=upload_content_type,
		)
	if content_type.startswith("application/json") or not content_type:
		try:
			payload = await request.json()
		except Exception as error:
			raise InvalidRequestError("请求体不是合法的 JSON") from error
		if not isinstance(payload, dict):
			raise InvalidRequestError("请求体必须是 JSON 对象")
		normalized_payload = {str(key): value for key, value in payload.items()}
		return normalized_payload, YoloXInferenceInputSource(
			input_uri=normalized_payload.get("input_uri") if isinstance(normalized_payload.get("input_uri"), str) else None,
			image_base64=normalized_payload.get("image_base64") if isinstance(normalized_payload.get("image_base64"), str) else None,
		)
	raise InvalidRequestError(
		"当前仅支持 application/json 或 multipart/form-data 推理请求",
		details={"content_type": content_type},
	)


def _resolve_http_request_id(request: Request, *, prefix: str) -> str:
	"""解析一个稳定的 HTTP 请求 id，用于临时输入和同步结果输出路径。"""

	request_id = getattr(request.state, "request_id", None)
	if isinstance(request_id, str) and request_id.strip():
		return f"{prefix}-{request_id.strip()}"
	return f"{prefix}-{uuid4().hex}"


def _resolve_requested_score_threshold(value: float | None) -> float:
	"""解析推理阈值；未提供时回落到默认值。"""

	if isinstance(value, int | float):
		threshold = float(value)
	else:
		threshold = _DEFAULT_INFERENCE_SCORE_THRESHOLD
	if threshold < 0 or threshold > 1:
		raise InvalidRequestError(
			"score_threshold 必须位于 0 到 1 之间",
			details={"score_threshold": threshold},
		)
	return threshold


def _read_optional_form_str(form: object, key: str) -> str | None:
	"""从 multipart form 中读取可选字符串字段。"""

	if not hasattr(form, "get"):
		return None
	value = form.get(key)
	if isinstance(value, str) and value.strip():
		return value.strip()
	return None


def _parse_optional_form_float(value: object, *, field_name: str) -> float | None:
	"""把 multipart form 字段解析为可选浮点数。"""

	if value is None or value == "":
		return None
	if isinstance(value, int | float):
		return float(value)
	if isinstance(value, str):
		try:
			return float(value.strip())
		except ValueError as error:
			raise InvalidRequestError(
				f"{field_name} 必须是合法数字",
				details={field_name: value},
			) from error
	raise InvalidRequestError(
		f"{field_name} 必须是合法数字",
		details={field_name: value},
	)


def _parse_optional_form_bool(value: object, *, field_name: str, default: bool) -> bool:
	"""把 multipart form 字段解析为布尔值。"""

	if value is None or value == "":
		return default
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		normalized = value.strip().lower()
		if normalized in {"1", "true", "yes", "on"}:
			return True
		if normalized in {"0", "false", "no", "off"}:
			return False
	raise InvalidRequestError(
		f"{field_name} 必须是合法布尔值",
		details={field_name: value},
	)


def _parse_optional_form_json_dict(value: object, *, field_name: str) -> dict[str, object]:
	"""把 multipart form 中的 JSON 字段解析为字典。"""

	if value is None or value == "":
		return {}
	if isinstance(value, dict):
		return {str(key): item for key, item in value.items()}
	if isinstance(value, str):
		try:
			parsed = json.loads(value)
		except json.JSONDecodeError as error:
			raise InvalidRequestError(
				f"{field_name} 不是合法 JSON",
				details={field_name: value},
			) from error
		if isinstance(parsed, dict):
			return {str(key): item for key, item in parsed.items()}
	raise InvalidRequestError(
		f"{field_name} 必须是 JSON 对象",
		details={field_name: value},
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
		instance_id=_read_optional_str(result, "instance_id")
		or _read_optional_str(result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {}, "instance_id"),
		model_version_id=_read_optional_str(result, "model_version_id")
		or _read_optional_str(metadata, "model_version_id"),
		model_build_id=_read_optional_str(result, "model_build_id")
		or _read_optional_str(metadata, "model_build_id"),
		input_uri=_read_optional_str(task_spec, "input_uri")
		or _read_optional_str(result, "input_uri"),
		input_source_kind=_read_optional_str(task_spec, "input_source_kind")
		or _read_optional_str(result, "input_source_kind"),
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