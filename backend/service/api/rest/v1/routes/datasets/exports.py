"""数据集导出 API。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import FileResponse

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory, get_unit_of_work
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.datasets.exports import DatasetExportRequest
from backend.service.application.datasets.exports.delivery import SqlAlchemyDatasetExportDeliveryService
from backend.service.application.datasets.tasks import SqlAlchemyDatasetExportTaskService
from backend.service.application.errors import PermissionDeniedError, ResourceNotFoundError
from backend.service.application.unit_of_work import UnitOfWork
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

from .responses import (
	_build_dataset_export_format_catalog_response,
	_build_dataset_export_package_response,
	_build_dataset_export_response,
)
from .schemas import (
	DatasetExportCreateRequestBody,
	DatasetExportDetailResponse,
	DatasetExportFormatCatalogResponse,
	DatasetExportPackageResponse,
	DatasetExportSubmissionResponse,
	DatasetExportSummaryResponse,
)


dataset_exports_router = APIRouter()


@dataset_exports_router.get(
	"/export-formats",
	response_model=DatasetExportFormatCatalogResponse,
)
def get_dataset_export_format_catalog(
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))],
) -> DatasetExportFormatCatalogResponse:
	"""返回当前公开的数据集导出格式规则。"""

	return _build_dataset_export_format_catalog_response()


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
	"/exports",
	response_model=list[DatasetExportSummaryResponse],
)
def list_project_dataset_exports(
	project_id: Annotated[str, Query(description="所属 Project id")],
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))],
	unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
	task_type: Annotated[str | None, Query(description="按 task_type 过滤")] = None,
	status_value: Annotated[str | None, Query(alias="status", description="按状态过滤")] = None,
	limit: Annotated[int, Query(ge=1, le=500, description="返回上限")] = 200,
) -> list[DatasetExportSummaryResponse]:
	"""按 Project 返回导出记录列表。"""

	if principal.project_ids and project_id not in principal.project_ids:
		raise PermissionDeniedError(
			"当前主体无权访问该 Project",
			details={"project_id": project_id},
		)

	normalized_task_type = task_type.strip().lower() if isinstance(task_type, str) else None
	normalized_status = status_value.strip().lower() if isinstance(status_value, str) else None
	dataset_exports = unit_of_work.dataset_exports.list_dataset_exports_by_project(project_id)
	visible_exports = [
		dataset_export
		for dataset_export in dataset_exports
		if _project_visible(principal=principal, project_id=dataset_export.project_id)
		and (normalized_task_type is None or dataset_export.task_type.strip().lower() == normalized_task_type)
		and (normalized_status is None or dataset_export.status.strip().lower() == normalized_status)
	]
	visible_exports.sort(
		key=lambda item: (item.created_at, item.dataset_export_id),
		reverse=True,
	)
	return [
		_build_dataset_export_response(dataset_export)
		for dataset_export in visible_exports[:limit]
	]


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


@dataset_exports_router.post(
	"/exports/{dataset_export_id}/package",
	response_model=DatasetExportPackageResponse,
)
def package_dataset_export(
	dataset_export_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:write"))],
	unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DatasetExportPackageResponse:
	"""为指定 DatasetExport 生成可下载 zip 包。"""

	visible_export = _require_visible_dataset_export(
		unit_of_work=unit_of_work,
		principal=principal,
		dataset_export_id=dataset_export_id,
	)
	delivery_service = SqlAlchemyDatasetExportDeliveryService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
	)
	package = delivery_service.package_export(visible_export.dataset_export_id)
	return _build_dataset_export_package_response(package)


@dataset_exports_router.get("/exports/{dataset_export_id}/download")
def download_dataset_export(
	dataset_export_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))],
	unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> FileResponse:
	"""下载指定 DatasetExport 的 zip 包。"""

	visible_export = _require_visible_dataset_export(
		unit_of_work=unit_of_work,
		principal=principal,
		dataset_export_id=dataset_export_id,
	)
	delivery_service = SqlAlchemyDatasetExportDeliveryService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
	)
	package, package_path = delivery_service.resolve_package_file(visible_export.dataset_export_id)
	return FileResponse(
		path=package_path,
		media_type="application/zip",
		filename=package.package_file_name,
	)


@dataset_exports_router.get("/exports/{dataset_export_id}/manifest")
def download_dataset_export_manifest(
	dataset_export_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))],
	unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> FileResponse:
	"""下载指定 DatasetExport 的 manifest 文件。"""

	visible_export = _require_visible_dataset_export(
		unit_of_work=unit_of_work,
		principal=principal,
		dataset_export_id=dataset_export_id,
	)
	delivery_service = SqlAlchemyDatasetExportDeliveryService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
	)
	_, manifest_path = delivery_service.resolve_manifest_file(visible_export.dataset_export_id)
	return FileResponse(
		path=manifest_path,
		media_type="application/json",
		filename=f"{visible_export.dataset_export_id}-manifest.json",
	)


def _project_visible(*, principal: AuthenticatedPrincipal, project_id: str) -> bool:
	"""判断当前主体是否可见指定 Project。"""

	if not principal.project_ids:
		return True

	return project_id in principal.project_ids


def _require_visible_dataset_export(
	*,
	unit_of_work: UnitOfWork,
	principal: AuthenticatedPrincipal,
	dataset_export_id: str,
) -> DatasetExport:
	"""读取并校验当前主体可见的 DatasetExport。"""

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

	return dataset_export

