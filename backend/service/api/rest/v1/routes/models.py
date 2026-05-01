"""模型 REST 路由分组。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import (
	InvalidRequestError,
	PermissionDeniedError,
	ResourceNotFoundError,
	ServiceConfigurationError,
)
from backend.service.application.models.yolox_model_service import (
	PlatformBaseModelBuildView,
	PlatformBaseModelDetailView,
	PlatformBaseModelFileView,
	PlatformBaseModelSummaryView,
	PlatformBaseModelVersionDetailView,
	PlatformBaseModelVersionSummaryView,
	SqlAlchemyYoloXModelService,
)
from backend.service.application.models.yolox_training_service import (
	SqlAlchemyYoloXTrainingTaskService,
	YOLOX_TRAINING_TASK_KIND,
	YoloXTrainingTaskRequest,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


models_router = APIRouter(prefix="/models", tags=["models"])

YoloXTrainingOutputFileName = Literal[
	"train-metrics",
	"validation-metrics",
	"summary",
	"labels",
	"best-checkpoint",
	"latest-checkpoint",
]

YoloXTrainingOutputFileKind = Literal["json", "text", "checkpoint"]

_YOLOX_TRAINING_OUTPUT_FILE_SPECS: dict[YoloXTrainingOutputFileName, dict[str, str]] = {
	"train-metrics": {
		"object_key_field": "metrics_object_key",
		"relative_path": "artifacts/reports/train-metrics.json",
		"file_kind": "json",
	},
	"validation-metrics": {
		"object_key_field": "validation_metrics_object_key",
		"relative_path": "artifacts/reports/validation-metrics.json",
		"file_kind": "json",
	},
	"summary": {
		"object_key_field": "summary_object_key",
		"relative_path": "artifacts/training-summary.json",
		"file_kind": "json",
	},
	"labels": {
		"object_key_field": "labels_object_key",
		"relative_path": "artifacts/labels.txt",
		"file_kind": "text",
	},
	"best-checkpoint": {
		"object_key_field": "checkpoint_object_key",
		"relative_path": "artifacts/checkpoints/best_ckpt.pth",
		"file_kind": "checkpoint",
	},
	"latest-checkpoint": {
		"object_key_field": "latest_checkpoint_object_key",
		"relative_path": "artifacts/checkpoints/latest_ckpt.pth",
		"file_kind": "checkpoint",
	},
}

_YOLOX_TRAINING_OUTPUT_FILE_ORDER: tuple[YoloXTrainingOutputFileName, ...] = (
	"train-metrics",
	"validation-metrics",
	"summary",
	"labels",
	"best-checkpoint",
	"latest-checkpoint",
)


class YoloXTrainingTaskCreateRequestBody(BaseModel):
	"""描述 YOLOX 训练任务创建请求体。"""

	project_id: str = Field(description="所属 Project id")
	dataset_export_id: str | None = Field(default=None, description="训练输入使用的 DatasetExport id")
	dataset_export_manifest_key: str | None = Field(default=None, description="训练输入使用的导出 manifest object key")
	recipe_id: str = Field(description="训练 recipe id")
	model_scale: Literal["nano", "tiny", "s", "m", "l", "x"] = Field(description="训练目标的模型 scale")
	output_model_name: str = Field(description="训练后登记的模型名")
	warm_start_model_version_id: str | None = Field(default=None, description="warm start 使用的 ModelVersion id")
	evaluation_interval: int | None = Field(default=5, ge=1, description="每隔多少轮执行一次真实验证评估")
	max_epochs: int | None = Field(default=None, description="最大训练轮数")
	batch_size: int | None = Field(default=None, description="batch size")
	gpu_count: int | None = Field(default=None, ge=1, description="请求参与训练的 GPU 数量")
	precision: Literal["fp16", "fp32"] | None = Field(
		default=None,
		description="请求使用的训练 precision",
	)
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
	evaluation_interval: int | None = Field(default=None, description="真实验证评估周期")
	gpu_count: int | None = Field(default=None, description="请求参与训练的 GPU 数量")
	precision: str | None = Field(default=None, description="请求使用的训练 precision")
	output_model_name: str | None = Field(default=None, description="训练输出模型名")
	model_version_id: str | None = Field(default=None, description="训练输出登记后的 ModelVersion id")
	output_object_prefix: str | None = Field(default=None, description="训练输出目录前缀")
	checkpoint_object_key: str | None = Field(default=None, description="checkpoint 文件 object key")
	latest_checkpoint_object_key: str | None = Field(default=None, description="最新 checkpoint 文件 object key")
	labels_object_key: str | None = Field(default=None, description="标签文件 object key")
	metrics_object_key: str | None = Field(default=None, description="训练指标文件 object key")
	validation_metrics_object_key: str | None = Field(default=None, description="验证指标文件 object key")
	summary_object_key: str | None = Field(default=None, description="训练摘要文件 object key")
	best_metric_name: str | None = Field(default=None, description="最佳指标名称")
	best_metric_value: float | None = Field(default=None, description="最佳指标值")
	training_summary: dict[str, object] = Field(default_factory=dict, description="训练摘要")


class YoloXTrainingTaskDetailResponse(YoloXTrainingTaskSummaryResponse):
	"""描述 YOLOX 训练任务详情响应。"""

	task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
	events: list[YoloXTrainingTaskEventResponse] = Field(default_factory=list, description="任务事件列表")


class YoloXTrainingMetricsFileResponse(BaseModel):
	"""描述训练 JSON 输出文件读取响应。"""

	file_status: Literal["pending", "ready"] = Field(description="训练输出文件状态")
	task_state: str = Field(description="当前训练任务状态")
	object_key: str | None = Field(default=None, description="训练输出文件 object key")
	payload: dict[str, object] = Field(default_factory=dict, description="JSON 文件内容；未生成时为空对象")


class YoloXTrainingOutputFileSummaryResponse(BaseModel):
	"""描述单个训练输出文件的读取状态。"""

	file_name: YoloXTrainingOutputFileName = Field(description="训练输出文件名称")
	file_kind: YoloXTrainingOutputFileKind = Field(description="训练输出文件类型")
	file_status: Literal["pending", "ready"] = Field(description="训练输出文件状态")
	task_state: str = Field(description="当前训练任务状态")
	object_key: str | None = Field(default=None, description="训练输出文件 object key")
	size_bytes: int | None = Field(default=None, description="文件字节大小")
	updated_at: str | None = Field(default=None, description="最后更新时间")


class YoloXTrainingOutputFileDetailResponse(YoloXTrainingOutputFileSummaryResponse):
	"""描述单个训练输出文件的读取结果。"""

	payload: dict[str, object] = Field(default_factory=dict, description="JSON 文件内容；非 JSON 或未生成时为空对象")
	text_content: str | None = Field(default=None, description="文本文件内容；非文本或未生成时为空")
	lines: list[str] = Field(default_factory=list, description="文本文件按行拆分后的内容；非文本或未生成时为空列表")


class PlatformBaseModelFileResponse(BaseModel):
	"""描述平台基础模型详情中的文件条目。"""

	file_id: str = Field(description="文件记录 id")
	project_id: str | None = Field(default=None, description="所属 Project id；平台基础模型文件时为空")
	scope_kind: str = Field(description="文件所属模型作用域类型")
	model_id: str = Field(description="所属 Model id")
	model_version_id: str | None = Field(default=None, description="所属 ModelVersion id")
	model_build_id: str | None = Field(default=None, description="所属 ModelBuild id")
	file_type: str = Field(description="文件类型")
	logical_name: str = Field(description="文件逻辑名")
	storage_uri: str = Field(description="文件存储 URI")
	metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class PlatformBaseModelVersionSummaryResponse(BaseModel):
	"""描述平台基础模型列表中的版本摘要。"""

	model_version_id: str = Field(description="ModelVersion id")
	source_kind: str = Field(description="版本来源类型")
	dataset_version_id: str | None = Field(default=None, description="关联 DatasetVersion id")
	training_task_id: str | None = Field(default=None, description="关联训练任务 id")
	parent_version_id: str | None = Field(default=None, description="父 ModelVersion id")
	file_ids: tuple[str, ...] = Field(default_factory=tuple, description="关联文件 id 列表")
	metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
	checkpoint_file_id: str | None = Field(default=None, description="checkpoint 文件 id")
	checkpoint_storage_uri: str | None = Field(default=None, description="checkpoint 存储 URI")
	catalog_manifest_object_key: str | None = Field(default=None, description="预训练目录 manifest object key")


class PlatformBaseModelVersionDetailResponse(PlatformBaseModelVersionSummaryResponse):
	"""描述平台基础模型详情中的版本条目。"""

	files: list[PlatformBaseModelFileResponse] = Field(default_factory=list, description="版本文件列表")


class PlatformBaseModelBuildResponse(BaseModel):
	"""描述平台基础模型详情中的构建条目。"""

	model_build_id: str = Field(description="ModelBuild id")
	source_model_version_id: str = Field(description="来源 ModelVersion id")
	build_format: str = Field(description="构建格式")
	runtime_profile_id: str | None = Field(default=None, description="目标 RuntimeProfile id")
	conversion_task_id: str | None = Field(default=None, description="来源转换任务 id")
	file_ids: tuple[str, ...] = Field(default_factory=tuple, description="关联文件 id 列表")
	metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
	files: list[PlatformBaseModelFileResponse] = Field(default_factory=list, description="构建文件列表")


class PlatformBaseModelSummaryResponse(BaseModel):
	"""描述平台基础模型列表项。"""

	model_id: str = Field(description="Model id")
	project_id: str | None = Field(default=None, description="所属 Project id；平台基础模型时为空")
	scope_kind: str = Field(description="模型作用域类型")
	model_name: str = Field(description="模型名")
	model_type: str = Field(description="模型类型名称")
	task_type: str = Field(description="任务类型")
	model_scale: str = Field(description="模型 scale")
	labels_file_id: str | None = Field(default=None, description="标签文件 id")
	metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
	version_count: int = Field(description="关联 ModelVersion 数量")
	build_count: int = Field(description="关联 ModelBuild 数量")
	available_versions: list[PlatformBaseModelVersionSummaryResponse] = Field(
		default_factory=list,
		description="可用于 warm start 的版本摘要列表",
	)


class PlatformBaseModelDetailResponse(PlatformBaseModelSummaryResponse):
	"""描述平台基础模型详情响应。"""

	versions: list[PlatformBaseModelVersionDetailResponse] = Field(default_factory=list, description="完整版本列表")
	builds: list[PlatformBaseModelBuildResponse] = Field(default_factory=list, description="完整构建列表")


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
			evaluation_interval=body.evaluation_interval,
			max_epochs=body.max_epochs,
			batch_size=body.batch_size,
			gpu_count=body.gpu_count,
			precision=body.precision,
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
	"/platform-base",
	response_model=list[PlatformBaseModelSummaryResponse],
)
def list_platform_base_models(
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	model_name: Annotated[str | None, Query(description="模型名筛选")] = None,
	model_scale: Annotated[str | None, Query(description="模型 scale 筛选")] = None,
	task_type: Annotated[str | None, Query(description="任务类型筛选")] = None,
	limit: Annotated[int, Query(ge=1, le=200, description="最大返回数量")] = 100,
) -> list[PlatformBaseModelSummaryResponse]:
	"""列出当前可见的平台基础模型。"""

	_ = principal
	service = SqlAlchemyYoloXModelService(session_factory=session_factory)
	models = service.list_platform_base_models(
		model_name=model_name,
		model_scale=model_scale,
		task_type=task_type,
		limit=limit,
	)
	return [_build_platform_base_model_summary_response(model) for model in models]


@models_router.get(
	"/platform-base/{model_id}",
	response_model=PlatformBaseModelDetailResponse,
)
def get_platform_base_model_detail(
	model_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> PlatformBaseModelDetailResponse:
	"""按 id 返回单个平台基础模型详情。"""

	_ = principal
	service = SqlAlchemyYoloXModelService(session_factory=session_factory)
	model_detail = service.get_platform_base_model_detail(model_id)
	if model_detail is None:
		raise ResourceNotFoundError(
			"找不到指定的平台基础模型",
			details={"model_id": model_id},
		)

	return _build_platform_base_model_detail_response(model_detail)


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

	task_detail = _require_visible_yolox_training_task(
		principal=principal,
		task_id=task_id,
		session_factory=session_factory,
		include_events=include_events,
	)

	return _build_yolox_training_task_detail_response(task_detail.task, tuple(task_detail.events))


@models_router.post(
	"/yolox/training-tasks/{task_id}/save",
	response_model=YoloXTrainingTaskDetailResponse,
)
def request_yolox_training_save(
	task_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> YoloXTrainingTaskDetailResponse:
	"""为运行中的 YOLOX 训练任务请求一次手动保存。"""

	_require_visible_yolox_training_task(
		principal=principal,
		task_id=task_id,
		session_factory=session_factory,
		include_events=False,
	)
	service = SqlAlchemyYoloXTrainingTaskService(session_factory=session_factory)
	task_detail = service.request_training_save(task_id, requested_by=principal.principal_id)
	return _build_yolox_training_task_detail_response(task_detail.task, tuple(task_detail.events))


@models_router.post(
	"/yolox/training-tasks/{task_id}/pause",
	response_model=YoloXTrainingTaskDetailResponse,
)
def request_yolox_training_pause(
	task_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> YoloXTrainingTaskDetailResponse:
	"""为运行中的 YOLOX 训练任务请求暂停。"""

	_require_visible_yolox_training_task(
		principal=principal,
		task_id=task_id,
		session_factory=session_factory,
		include_events=False,
	)
	service = SqlAlchemyYoloXTrainingTaskService(session_factory=session_factory)
	task_detail = service.request_training_pause(task_id, requested_by=principal.principal_id)
	return _build_yolox_training_task_detail_response(task_detail.task, tuple(task_detail.events))


@models_router.post(
	"/yolox/training-tasks/{task_id}/resume",
	response_model=YoloXTrainingTaskSubmissionResponse,
)
def resume_yolox_training_task(
	task_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> YoloXTrainingTaskSubmissionResponse:
	"""把一个 paused 的 YOLOX 训练任务重新入队执行。"""

	_require_visible_yolox_training_task(
		principal=principal,
		task_id=task_id,
		session_factory=session_factory,
		include_events=False,
	)
	service = SqlAlchemyYoloXTrainingTaskService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		queue_backend=queue_backend,
	)
	submission = service.resume_training_task(task_id, resumed_by=principal.principal_id)
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
	"/yolox/training-tasks/{task_id}/validation-metrics",
	response_model=YoloXTrainingMetricsFileResponse,
)
def get_yolox_training_validation_metrics(
	task_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	) -> YoloXTrainingMetricsFileResponse:
	"""按任务 id 返回当前 YOLOX 训练的验证快照。"""

	task_detail = _require_visible_yolox_training_task(
		principal=principal,
		task_id=task_id,
		session_factory=session_factory,
		include_events=False,
	)
	output_file = _read_yolox_training_output_file(
		task=task_detail.task,
		file_name="validation-metrics",
		dataset_storage=dataset_storage,
		strict_missing=True,
	)
	return _build_yolox_training_metrics_file_response(output_file)


@models_router.get(
	"/yolox/training-tasks/{task_id}/train-metrics",
	response_model=YoloXTrainingMetricsFileResponse,
)
def get_yolox_training_train_metrics(
	task_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	) -> YoloXTrainingMetricsFileResponse:
	"""按任务 id 返回当前 YOLOX 训练的训练指标快照。"""

	task_detail = _require_visible_yolox_training_task(
		principal=principal,
		task_id=task_id,
		session_factory=session_factory,
		include_events=False,
	)
	output_file = _read_yolox_training_output_file(
		task=task_detail.task,
		file_name="train-metrics",
		dataset_storage=dataset_storage,
		strict_missing=True,
	)
	return _build_yolox_training_metrics_file_response(output_file)


@models_router.get(
	"/yolox/training-tasks/{task_id}/output-files",
	response_model=list[YoloXTrainingOutputFileSummaryResponse],
)
def list_yolox_training_output_files(
	task_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> list[YoloXTrainingOutputFileSummaryResponse]:
	"""按任务 id 列出当前 YOLOX 训练输出文件状态。"""

	task_detail = _require_visible_yolox_training_task(
		principal=principal,
		task_id=task_id,
		session_factory=session_factory,
		include_events=False,
	)
	return [
		_build_yolox_training_output_file_summary_response(
			_read_yolox_training_output_file(
				task=task_detail.task,
				file_name=file_name,
				dataset_storage=dataset_storage,
				strict_missing=False,
			)
		)
		for file_name in _YOLOX_TRAINING_OUTPUT_FILE_ORDER
	]


@models_router.get(
	"/yolox/training-tasks/{task_id}/output-files/{file_name}",
	response_model=YoloXTrainingOutputFileDetailResponse,
)
def get_yolox_training_output_file_detail(
	task_id: str,
	file_name: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> YoloXTrainingOutputFileDetailResponse:
	"""按任务 id 和文件名返回单个训练输出文件的状态与内容。"""

	task_detail = _require_visible_yolox_training_task(
		principal=principal,
		task_id=task_id,
		session_factory=session_factory,
		include_events=False,
	)
	return _read_yolox_training_output_file(
		task=task_detail.task,
		file_name=_parse_yolox_training_output_file_name(file_name),
		dataset_storage=dataset_storage,
		strict_missing=False,
	)


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


def _require_visible_yolox_training_task(
	*,
	principal: AuthenticatedPrincipal,
	task_id: str,
	session_factory: SessionFactory,
	include_events: bool,
):
	"""读取并校验当前主体可见的 YOLOX 训练任务。"""

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
	return task_detail


def _matches_yolox_training_filters(
	*,
	task: object,
	dataset_export_id: str | None,
	dataset_export_manifest_key: str | None,
) -> bool:
	"""判断 YOLOX 训练任务是否满足额外筛选条件。"""

	task_spec = dict(task.task_spec)
	manifest_object_key = task_spec.get("manifest_object_key")
	if dataset_export_id is not None and task_spec.get("dataset_export_id") != dataset_export_id:
		return False
	if (
		dataset_export_manifest_key is not None
		and task_spec.get("dataset_export_manifest_key") != dataset_export_manifest_key
		and manifest_object_key != dataset_export_manifest_key
	):
		return False

	return True


def _build_yolox_training_task_summary_response(task: object) -> YoloXTrainingTaskSummaryResponse:
	"""把 YOLOX 训练 TaskRecord 转成摘要响应。"""

	task_spec = dict(task.task_spec)
	result = dict(task.result)
	metadata = dict(task.metadata)
	training_summary = result.get("summary")
	training_summary_payload = dict(training_summary) if isinstance(training_summary, dict) else {}
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
		dataset_export_manifest_key=(
			_read_optional_str(task_spec, "dataset_export_manifest_key")
			or _read_optional_str(task_spec, "manifest_object_key")
		),
		dataset_version_id=_read_optional_str(result, "dataset_version_id")
		or _read_optional_str(metadata, "dataset_version_id"),
		format_id=_read_optional_str(result, "format_id")
		or _read_optional_str(metadata, "format_id"),
		recipe_id=_read_optional_str(task_spec, "recipe_id"),
		model_scale=_read_optional_str(task_spec, "model_scale"),
		evaluation_interval=_read_optional_int(task_spec, "evaluation_interval"),
		gpu_count=_read_optional_int(task_spec, "gpu_count"),
		precision=_read_optional_str(task_spec, "precision"),
		output_model_name=_read_optional_str(task_spec, "output_model_name"),
		model_version_id=_read_optional_str(result, "model_version_id")
		or _read_optional_str(training_summary_payload, "model_version_id"),
		output_object_prefix=(
			_read_optional_str(result, "output_object_prefix")
			or _read_optional_str(metadata, "output_object_prefix")
		),
		checkpoint_object_key=_read_optional_str(result, "checkpoint_object_key"),
		latest_checkpoint_object_key=_read_optional_str(result, "latest_checkpoint_object_key"),
		labels_object_key=_read_optional_str(result, "labels_object_key"),
		metrics_object_key=_read_optional_str(result, "metrics_object_key"),
		validation_metrics_object_key=_read_optional_str(result, "validation_metrics_object_key"),
		summary_object_key=_read_optional_str(result, "summary_object_key"),
		best_metric_name=_read_optional_str(result, "best_metric_name"),
		best_metric_value=(
			float(best_metric_value)
			if isinstance(best_metric_value, int | float)
			else None
		),
		training_summary=training_summary_payload,
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


def _build_yolox_training_metrics_file_response(
	output_file: YoloXTrainingOutputFileDetailResponse,
) -> YoloXTrainingMetricsFileResponse:
	"""把训练 JSON 输出文件详情转换为统一 metrics 响应。"""

	return YoloXTrainingMetricsFileResponse(
		file_status=output_file.file_status,
		task_state=output_file.task_state,
		object_key=output_file.object_key,
		payload=dict(output_file.payload),
	)


def _parse_yolox_training_output_file_name(file_name: str) -> YoloXTrainingOutputFileName:
	"""校验训练输出文件名称是否属于公开资源组。"""

	if file_name in _YOLOX_TRAINING_OUTPUT_FILE_SPECS:
		return file_name  # type: ignore[return-value]
	raise ResourceNotFoundError(
		"找不到指定的训练输出文件",
		details={"file_name": file_name},
	)


def _resolve_yolox_training_output_file_object_key(
	*,
	task: object,
	file_name: YoloXTrainingOutputFileName,
) -> str | None:
	"""解析训练输出文件当前可用的 object key。"""

	result = dict(task.result)
	metadata = dict(task.metadata)
	training_summary = result.get("summary")
	training_summary_payload = dict(training_summary) if isinstance(training_summary, dict) else {}
	spec = _YOLOX_TRAINING_OUTPUT_FILE_SPECS[file_name]
	object_key_field = spec["object_key_field"]
	resolved_object_key = (
		_read_optional_str(result, object_key_field)
		or _read_optional_str(metadata, object_key_field)
		or _read_optional_str(training_summary_payload, object_key_field)
	)
	if resolved_object_key is not None:
		return resolved_object_key
	output_object_prefix = (
		_read_optional_str(result, "output_object_prefix")
		or _read_optional_str(metadata, "output_object_prefix")
		or _read_optional_str(training_summary_payload, "output_object_prefix")
	)
	if output_object_prefix is None:
		return None
	return f"{output_object_prefix}/{spec['relative_path']}"


def _build_yolox_training_output_file_summary_response(
	output_file: YoloXTrainingOutputFileDetailResponse,
) -> YoloXTrainingOutputFileSummaryResponse:
	"""把训练输出文件详情压缩成列表项响应。"""

	return YoloXTrainingOutputFileSummaryResponse(
		file_name=output_file.file_name,
		file_kind=output_file.file_kind,
		file_status=output_file.file_status,
		task_state=output_file.task_state,
		object_key=output_file.object_key,
		size_bytes=output_file.size_bytes,
		updated_at=output_file.updated_at,
	)


def _read_yolox_training_output_file(
	*,
	task: object,
	file_name: YoloXTrainingOutputFileName,
	dataset_storage: LocalDatasetStorage,
	strict_missing: bool,
) -> YoloXTrainingOutputFileDetailResponse:
	"""读取训练输出文件的状态、元数据和可读内容。"""

	task_state = task.state
	spec = _YOLOX_TRAINING_OUTPUT_FILE_SPECS[file_name]
	file_kind = spec["file_kind"]
	object_key = _resolve_yolox_training_output_file_object_key(task=task, file_name=file_name)
	if object_key is None:
		if strict_missing and task_state not in {"queued", "running"}:
			raise ResourceNotFoundError(
				"当前训练任务缺少训练输出文件",
				details={
					"task_id": task.task_id,
					"file_name": file_name,
				},
			)
		return YoloXTrainingOutputFileDetailResponse(
			file_name=file_name,
			file_kind=file_kind,  # type: ignore[arg-type]
			file_status="pending",
			task_state=task_state,
			object_key=None,
		)

	file_path = dataset_storage.resolve(object_key)
	if not file_path.is_file():
		if strict_missing and task_state not in {"queued", "running"}:
			raise ResourceNotFoundError(
				"当前训练任务缺少训练输出文件",
				details={
					"task_id": task.task_id,
					"file_name": file_name,
					"object_key": object_key,
				},
			)
		return YoloXTrainingOutputFileDetailResponse(
			file_name=file_name,
			file_kind=file_kind,  # type: ignore[arg-type]
			file_status="pending",
			task_state=task_state,
			object_key=object_key,
		)

	file_stat = file_path.stat()
	updated_at = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc).isoformat()
	payload: dict[str, object] = {}
	text_content: str | None = None
	lines: list[str] = []
	if file_kind == "json":
		json_payload = dataset_storage.read_json(object_key)
		if not isinstance(json_payload, dict):
			raise ServiceConfigurationError(
				"训练输出文件内容不合法",
				details={
					"task_id": task.task_id,
					"file_name": file_name,
					"object_key": object_key,
				},
			)
		payload = dict(json_payload)
	elif file_kind == "text":
		text_content = file_path.read_text(encoding="utf-8")
		lines = text_content.splitlines()

	return YoloXTrainingOutputFileDetailResponse(
		file_name=file_name,
		file_kind=file_kind,  # type: ignore[arg-type]
		file_status="ready",
		task_state=task_state,
		object_key=object_key,
		size_bytes=file_stat.st_size,
		updated_at=updated_at,
		payload=payload,
		text_content=text_content,
		lines=lines,
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


def _build_platform_base_model_summary_response(
	model: PlatformBaseModelSummaryView,
) -> PlatformBaseModelSummaryResponse:
	"""把平台基础模型摘要视图转换为响应对象。"""

	return PlatformBaseModelSummaryResponse(
		model_id=model.model_id,
		project_id=model.project_id,
		scope_kind=model.scope_kind,
		model_name=model.model_name,
		model_type=model.model_type,
		task_type=model.task_type,
		model_scale=model.model_scale,
		labels_file_id=model.labels_file_id,
		metadata=dict(model.metadata),
		version_count=model.version_count,
		build_count=model.build_count,
		available_versions=[
			_build_platform_base_model_version_summary_response(version)
			for version in model.available_versions
		],
	)


def _build_platform_base_model_detail_response(
	model: PlatformBaseModelDetailView,
) -> PlatformBaseModelDetailResponse:
	"""把平台基础模型详情视图转换为响应对象。"""

	return PlatformBaseModelDetailResponse(
		**_build_platform_base_model_summary_response(model).model_dump(),
		versions=[_build_platform_base_model_version_detail_response(version) for version in model.versions],
		builds=[_build_platform_base_model_build_response(build) for build in model.builds],
	)


def _build_platform_base_model_version_summary_response(
	version: PlatformBaseModelVersionSummaryView,
) -> PlatformBaseModelVersionSummaryResponse:
	"""把平台基础模型版本摘要视图转换为响应对象。"""

	return PlatformBaseModelVersionSummaryResponse(
		model_version_id=version.model_version_id,
		source_kind=version.source_kind,
		dataset_version_id=version.dataset_version_id,
		training_task_id=version.training_task_id,
		parent_version_id=version.parent_version_id,
		file_ids=version.file_ids,
		metadata=dict(version.metadata),
		checkpoint_file_id=version.checkpoint_file_id,
		checkpoint_storage_uri=version.checkpoint_storage_uri,
		catalog_manifest_object_key=version.catalog_manifest_object_key,
	)


def _build_platform_base_model_version_detail_response(
	version: PlatformBaseModelVersionDetailView,
) -> PlatformBaseModelVersionDetailResponse:
	"""把平台基础模型版本详情视图转换为响应对象。"""

	return PlatformBaseModelVersionDetailResponse(
		**_build_platform_base_model_version_summary_response(version).model_dump(),
		files=[_build_platform_base_model_file_response(model_file) for model_file in version.files],
	)


def _build_platform_base_model_build_response(
	build: PlatformBaseModelBuildView,
) -> PlatformBaseModelBuildResponse:
	"""把平台基础模型构建视图转换为响应对象。"""

	return PlatformBaseModelBuildResponse(
		model_build_id=build.model_build_id,
		source_model_version_id=build.source_model_version_id,
		build_format=build.build_format,
		runtime_profile_id=build.runtime_profile_id,
		conversion_task_id=build.conversion_task_id,
		file_ids=build.file_ids,
		metadata=dict(build.metadata),
		files=[_build_platform_base_model_file_response(model_file) for model_file in build.files],
	)


def _build_platform_base_model_file_response(
	model_file: PlatformBaseModelFileView,
) -> PlatformBaseModelFileResponse:
	"""把平台基础模型文件视图转换为响应对象。"""

	return PlatformBaseModelFileResponse(
		file_id=model_file.file_id,
		project_id=model_file.project_id,
		scope_kind=model_file.scope_kind,
		model_id=model_file.model_id,
		model_version_id=model_file.model_version_id,
		model_build_id=model_file.model_build_id,
		file_type=model_file.file_type,
		logical_name=model_file.logical_name,
		storage_uri=model_file.storage_uri,
		metadata=dict(model_file.metadata),
	)


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
	"""从字典中读取可选字符串字段。"""

	value = payload.get(key)
	if isinstance(value, str) and value.strip():
		return value
	return None


def _read_optional_int(payload: dict[str, object], key: str) -> int | None:
	"""从字典中读取可选整数字段。"""

	value = payload.get(key)
	if isinstance(value, int):
		return value
	return None


def _read_optional_float(payload: dict[str, object], key: str) -> float | None:
	"""从字典中读取可选浮点数字段。"""

	value = payload.get(key)
	if isinstance(value, int | float):
		return float(value)
	return None