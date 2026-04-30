"""模型 REST 路由分组。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.application.errors import PermissionDeniedError
from backend.service.application.models.yolox_training_service import (
	SqlAlchemyYoloXTrainingTaskService,
	YoloXTrainingTaskRequest,
)
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