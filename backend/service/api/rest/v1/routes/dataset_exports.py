"""数据集导出 REST 路由分组。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory, get_unit_of_work
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.datasets.dataset_export import (
	DatasetExportRequest,
	SqlAlchemyDatasetExportTaskService,
)
from backend.service.application.errors import PermissionDeniedError, ResourceNotFoundError
from backend.service.application.unit_of_work import UnitOfWork
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


dataset_exports_router = APIRouter(prefix="/datasets", tags=["datasets"])


class DatasetExportCreateRequestBody(BaseModel):
	"""描述创建 DatasetExport 的请求体。"""

	project_id: str = Field(description="所属 Project id")
	dataset_id: str = Field(description="所属 Dataset id")
	dataset_version_id: str = Field(description="导出来源的 DatasetVersion id")
	format_id: str = Field(description="目标导出格式 id")
	display_name: str = Field(default="", description="可选的任务展示名称")
	output_object_prefix: str = Field(default="", description="可选的导出目录前缀")
	category_names: tuple[str, ...] = Field(default_factory=tuple, description="可选的导出类别名列表")
	include_test_split: bool = Field(default=True, description="是否包含 test split")


class DatasetExportSubmissionResponse(BaseModel):
	"""描述 DatasetExport 提交接口响应。"""

	dataset_export_id: str = Field(description="导出记录 id")
	task_id: str = Field(description="关联的任务 id")
	status: str = Field(description="导出状态")
	dataset_version_id: str = Field(description="导出来源的 DatasetVersion id")
	format_id: str = Field(description="目标导出格式 id")
	queue_name: str = Field(description="提交到的队列名称")
	queue_task_id: str = Field(description="队列任务 id")


class DatasetExportSummaryResponse(BaseModel):
	"""描述 DatasetExport 列表中的单条记录摘要。"""

	dataset_export_id: str = Field(description="导出记录 id")
	task_id: str | None = Field(default=None, description="关联的任务 id")
	dataset_id: str = Field(description="所属 Dataset id")
	project_id: str = Field(description="所属 Project id")
	dataset_version_id: str = Field(description="导出来源的 DatasetVersion id")
	format_id: str = Field(description="导出格式 id")
	task_type: str = Field(description="任务类型")
	status: str = Field(description="导出状态")
	created_at: str = Field(description="导出记录创建时间")
	include_test_split: bool = Field(description="是否包含 test split")
	export_path: str | None = Field(default=None, description="导出根目录 object key")
	manifest_object_key: str | None = Field(default=None, description="导出 manifest object key")
	split_names: tuple[str, ...] = Field(default_factory=tuple, description="导出产生的 split 列表")
	sample_count: int = Field(description="导出样本总数")
	category_names: tuple[str, ...] = Field(default_factory=tuple, description="导出类别名列表")
	queue_task_id: str | None = Field(default=None, description="关联的队列任务 id")
	error_message: str | None = Field(default=None, description="失败时的错误消息")
	metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class DatasetExportDetailResponse(DatasetExportSummaryResponse):
	"""描述 DatasetExport 查询接口返回的完整记录。"""


@dataset_exports_router.post("/exports", response_model=DatasetExportSubmissionResponse, status_code=status.HTTP_202_ACCEPTED)
def create_dataset_export(
	body: DatasetExportCreateRequestBody,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> DatasetExportSubmissionResponse:
	"""创建一个新的 DatasetExport 资源并提交后台导出任务。"""

	if principal.project_ids and body.project_id not in principal.project_ids:
		raise PermissionDeniedError(
			"当前主体无权访问该 Project",
			details={"project_id": body.project_id},
		)

	service = SqlAlchemyDatasetExportTaskService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		queue_backend=queue_backend,
	)
	submission = service.submit_export_task(
		DatasetExportRequest(
			project_id=body.project_id,
			dataset_id=body.dataset_id,
			dataset_version_id=body.dataset_version_id,
			format_id=body.format_id,
			output_object_prefix=body.output_object_prefix,
			category_names=body.category_names,
			include_test_split=body.include_test_split,
		),
		created_by=principal.principal_id,
		display_name=body.display_name,
	)

	return DatasetExportSubmissionResponse(
		dataset_export_id=submission.dataset_export_id,
		task_id=submission.task_id,
		status=submission.status,
		dataset_version_id=submission.dataset_version_id,
		format_id=submission.format_id,
		queue_name=submission.queue_name,
		queue_task_id=submission.queue_task_id,
	)


@dataset_exports_router.get(
	"/exports/{dataset_export_id}",
	response_model=DatasetExportDetailResponse,
)
def get_dataset_export_detail(
	dataset_export_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))],
	unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> DatasetExportDetailResponse:
	"""按 DatasetExport id 返回导出记录详情。"""

	dataset_export = unit_of_work.dataset_exports.get_dataset_export(dataset_export_id)
	if dataset_export is None:
		raise ResourceNotFoundError(
			"找不到指定的 DatasetExport",
			details={"dataset_export_id": dataset_export_id},
		)
	if not _project_visible(principal=principal, project_id=dataset_export.project_id):
		raise ResourceNotFoundError(
			"找不到指定的 DatasetExport",
			details={"dataset_export_id": dataset_export_id},
		)

	return _build_dataset_export_response(dataset_export)


@dataset_exports_router.get(
	"/{dataset_id}/versions/{dataset_version_id}/exports",
	response_model=list[DatasetExportSummaryResponse],
)
def list_dataset_exports(
	dataset_id: str,
	dataset_version_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))],
	unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> list[DatasetExportSummaryResponse]:
	"""按 DatasetVersion id 返回导出记录列表。"""

	dataset_exports = unit_of_work.dataset_exports.list_dataset_exports(dataset_version_id)
	visible_exports = [
		dataset_export
		for dataset_export in dataset_exports
		if dataset_export.dataset_id == dataset_id
		and _project_visible(principal=principal, project_id=dataset_export.project_id)
	]
	visible_exports.sort(
		key=lambda item: (item.created_at, item.dataset_export_id),
		reverse=True,
	)
	return [_build_dataset_export_response(dataset_export) for dataset_export in visible_exports]


def _project_visible(*, principal: AuthenticatedPrincipal, project_id: str) -> bool:
	"""判断当前主体是否可见指定 Project。"""

	if not principal.project_ids:
		return True

	return project_id in principal.project_ids


def _build_dataset_export_response(dataset_export: DatasetExport) -> DatasetExportDetailResponse:
	"""把 DatasetExport 转成显式响应模型。"""

	return DatasetExportDetailResponse(
		dataset_export_id=dataset_export.dataset_export_id,
		task_id=dataset_export.task_id,
		dataset_id=dataset_export.dataset_id,
		project_id=dataset_export.project_id,
		dataset_version_id=dataset_export.dataset_version_id,
		format_id=dataset_export.format_id,
		task_type=dataset_export.task_type,
		status=dataset_export.status,
		created_at=dataset_export.created_at,
		include_test_split=dataset_export.include_test_split,
		export_path=dataset_export.export_path,
		manifest_object_key=dataset_export.manifest_object_key,
		split_names=dataset_export.split_names,
		sample_count=dataset_export.sample_count,
		category_names=dataset_export.category_names,
		queue_task_id=_read_optional_str(dataset_export.metadata, "queue_task_id"),
		error_message=dataset_export.error_message,
		metadata=dict(dataset_export.metadata),
	)


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
	"""从字典中读取可选字符串字段。"""

	value = payload.get(key)
	if isinstance(value, str):
		return value

	return None