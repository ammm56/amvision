"""数据集导入 API。"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory, get_unit_of_work
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.datasets.imports import (
	DatasetImportRequest,
	SqlAlchemyDatasetImportService,
)
from backend.service.application.errors import (
	InvalidRequestError,
	PermissionDeniedError,
	ResourceNotFoundError,
)
from backend.service.application.unit_of_work import UnitOfWork
from backend.service.domain.datasets.dataset_import import (
	DatasetImport,
	DatasetFormatType,
	DatasetImportRequestedSplitStrategy,
	DatasetImportTaskType,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

from .responses import (
	_build_dataset_import_detail,
	_build_dataset_import_summary,
	_build_dataset_version_relation,
	_derive_processing_state,
	_read_optional_int,
	_read_optional_str,
)
from .schemas import (
	DatasetImportDetailResponse,
	DatasetImportSubmissionResponse,
	DatasetImportSummaryResponse,
	DatasetVersionRelationResponse,
)


dataset_imports_router = APIRouter()

DATASET_IMPORT_QUEUE_NAME = "dataset-imports"


@dataset_imports_router.post("/imports", response_model=DatasetImportSubmissionResponse, status_code=202)
async def import_dataset_zip(
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
	project_id: Annotated[str, Form()],
	dataset_id: Annotated[str, Form()],
	package: Annotated[UploadFile, File()],
	task_type: Annotated[DatasetImportTaskType, Form()],
	format_type: Annotated[DatasetFormatType | None, Form()] = None,
	split_strategy: Annotated[DatasetImportRequestedSplitStrategy | None, Form()] = None,
	class_map_json: Annotated[str | None, Form()] = None,
) -> DatasetImportSubmissionResponse:
	"""接收 zip 数据集压缩包并生成 DatasetImport 与 DatasetVersion。

	参数：
	- principal：具备 datasets:write scope 的调用主体。
	- session_factory：当前应用使用的数据库会话工厂。
	- dataset_storage：当前应用使用的数据集本地文件存储服务。
	- project_id：所属 Project id。
	- dataset_id：所属 Dataset id。
	- package：上传的 zip 数据集压缩包。
	- format_type：显式指定的数据集格式；为空时自动识别。
	- task_type：显式指定的任务类型。
	- split_strategy：显式指定的 split 策略。
	- class_map_json：类别映射的 JSON 字符串。

	返回：
	- 导入结果。
	"""

	if principal.project_ids and project_id not in principal.project_ids:
		raise PermissionDeniedError(
			"当前主体无权访问该 Project",
			details={"project_id": project_id},
		)

	class_map = _parse_class_map_json(class_map_json)
	service = SqlAlchemyDatasetImportService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
	)
	submitted_import = service.submit_dataset_import(
		DatasetImportRequest(
			project_id=project_id,
			dataset_id=dataset_id,
			package_file_name=package.filename or "dataset.zip",
			format_type=format_type,
			task_type=task_type,
			split_strategy=split_strategy,
			class_map=class_map,
			metadata={"principal_id": principal.principal_id},
		),
		package_file=package.file,
	)
	queue_task = queue_backend.enqueue(
		queue_name=DATASET_IMPORT_QUEUE_NAME,
		payload={"dataset_import_id": submitted_import.dataset_import_id},
		metadata={
			"project_id": project_id,
			"dataset_id": dataset_id,
		},
	)
	queued_import = service.mark_dataset_import_queued(
		submitted_import.dataset_import_id,
		queue_name=queue_task.queue_name,
		queue_task_id=queue_task.task_id,
	)

	return DatasetImportSubmissionResponse(
		dataset_import_id=queued_import.dataset_import_id,
		task_id=_read_optional_str(queued_import.metadata, "task_id"),
		status=queued_import.status,
		upload_state=_read_optional_str(queued_import.metadata, "upload_state") or "uploaded",
		processing_state=_derive_processing_state(queued_import),
		package_size=_read_optional_int(queued_import.metadata, "package_size") or 0,
		package_path=queued_import.package_path,
		staging_path=queued_import.staging_path,
		queue_name=queue_task.queue_name,
		queue_task_id=queue_task.task_id,
	)


@dataset_imports_router.get(
	"/imports",
	response_model=list[DatasetImportSummaryResponse],
)
def list_project_dataset_imports(
	project_id: Annotated[str, Query()],
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))],
	unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> list[DatasetImportSummaryResponse]:
	"""按 Project id 返回导入记录列表。

	数据集页面是项目级工作台，Dataset id 只是新导入时的目标 id。
	列表按 Project 展示可以避免导入到非默认 Dataset 后回到页面看不到记录。

	参数：
	- project_id：要查询的 Project id。
	- principal：具备 datasets:read scope 的调用主体。
	- unit_of_work：当前请求级 Unit of Work。

	返回：
	- 当前 Project 下的导入记录摘要列表。
	"""

	if not _project_visible(principal=principal, project_id=project_id):
		raise ResourceNotFoundError(
			"找不到指定的 Project",
			details={"project_id": project_id},
		)

	dataset_imports = unit_of_work.dataset_imports.list_dataset_imports_by_project(project_id)
	return [_build_dataset_import_summary(dataset_import) for dataset_import in dataset_imports]


@dataset_imports_router.get(
	"/{dataset_id}/imports",
	response_model=list[DatasetImportSummaryResponse],
)
def list_dataset_imports(
	dataset_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))],
	unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> list[DatasetImportSummaryResponse]:
	"""按 Dataset id 返回导入记录列表。

	参数：
	- dataset_id：要查询的 Dataset id。
	- principal：具备 datasets:read scope 的调用主体。
	- unit_of_work：当前请求级 Unit of Work。

	返回：
	- 当前 Dataset 下的导入记录摘要列表。
	"""

	dataset_imports = unit_of_work.dataset_imports.list_dataset_imports(dataset_id)
	visible_imports = [
		dataset_import
		for dataset_import in dataset_imports
		if _project_visible(principal=principal, project_id=dataset_import.project_id)
	]

	return [_build_dataset_import_summary(dataset_import) for dataset_import in visible_imports]


@dataset_imports_router.get(
	"/imports/{dataset_import_id}",
	response_model=DatasetImportDetailResponse,
)
def get_dataset_import_detail(
	dataset_import_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))],
	unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> DatasetImportDetailResponse:
	"""按 DatasetImport id 返回导入记录详情。

	参数：
	- dataset_import_id：要查询的 DatasetImport id。
	- principal：具备 datasets:read scope 的调用主体。
	- unit_of_work：当前请求级 Unit of Work。

	返回：
	- 导入记录、校验报告和版本关系详情。
	"""

	dataset_import = unit_of_work.dataset_imports.get_dataset_import(dataset_import_id)
	if dataset_import is None:
		raise ResourceNotFoundError(
			"找不到指定的 DatasetImport",
			details={"dataset_import_id": dataset_import_id},
		)
	if not _project_visible(principal=principal, project_id=dataset_import.project_id):
		raise ResourceNotFoundError(
			"找不到指定的 DatasetImport",
			details={"dataset_import_id": dataset_import_id},
		)

	dataset_version = None
	if dataset_import.dataset_version_id is not None:
		dataset_version = unit_of_work.datasets.get_dataset_version(dataset_import.dataset_version_id)

	return _build_dataset_import_detail(
		dataset_import=dataset_import,
		dataset_version=dataset_version,
	)


@dataset_imports_router.get(
	"/{dataset_id}/versions/{dataset_version_id}",
	response_model=DatasetVersionRelationResponse,
)
def get_dataset_version_relation(
	dataset_id: str,
	dataset_version_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))],
	unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> DatasetVersionRelationResponse:
	"""按 DatasetVersion id 返回版本摘要。

	参数：
	- dataset_id：所属 Dataset id。
	- dataset_version_id：要读取的 DatasetVersion id。
	- principal：具备 datasets:read scope 的调用主体。
	- unit_of_work：当前请求级 Unit of Work。

	返回：
	- DatasetVersion 摘要。
	"""

	dataset_version = unit_of_work.datasets.get_dataset_version(dataset_version_id)
	if dataset_version is None or dataset_version.dataset_id != dataset_id:
		raise ResourceNotFoundError(
			"找不到指定的 DatasetVersion",
			details={"dataset_version_id": dataset_version_id},
		)
	if not _project_visible(principal=principal, project_id=dataset_version.project_id):
		raise ResourceNotFoundError(
			"找不到指定的 DatasetVersion",
			details={"dataset_version_id": dataset_version_id},
		)

	return _build_dataset_version_relation(dataset_version)


@dataset_imports_router.delete(
	"/imports/{dataset_import_id}",
	status_code=204,
)
def delete_dataset_import(
	dataset_import_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:write"))],
	unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> None:
	"""删除一个已完成的 DatasetImport 记录。

	只有 completed 或 failed 状态的导入记录可以删除。

	参数：
	- dataset_import_id：要删除的 DatasetImport id。
	- principal：具备 datasets:write scope 的调用主体。
	- unit_of_work：当前请求级 Unit of Work。
	- dataset_storage：本地文件存储服务。
	"""

	dataset_import = unit_of_work.dataset_imports.get_dataset_import(dataset_import_id)
	if dataset_import is None:
		raise ResourceNotFoundError(
			"找不到指定的 DatasetImport",
			details={"dataset_import_id": dataset_import_id},
		)
	if not _project_visible(principal=principal, project_id=dataset_import.project_id):
		raise ResourceNotFoundError(
			"找不到指定的 DatasetImport",
			details={"dataset_import_id": dataset_import_id},
		)
	if dataset_import.status not in ("completed", "failed"):
		raise InvalidRequestError(
			"只能删除已完成或已失败的导入记录",
			details={"dataset_import_id": dataset_import_id, "status": dataset_import.status},
		)

	import_root = _resolve_dataset_import_root(dataset_import)
	if import_root is not None:
		dataset_storage.delete_tree(import_root)

	import_task_id = _read_optional_str(dataset_import.metadata, "task_id")
	if import_task_id is not None and import_task_id.strip():
		unit_of_work.tasks.delete_task(import_task_id)

	unit_of_work.dataset_imports.delete_dataset_import(dataset_import_id)
	unit_of_work.commit()


def _parse_class_map_json(class_map_json: str | None) -> dict[str, str]:
	"""把请求中的 class_map JSON 字符串解析为字典。

	参数：
	- class_map_json：类别映射 JSON 字符串。

	返回：
	- 解析后的类别映射字典。
	"""

	if class_map_json is None or not class_map_json.strip():
		return {}

	try:
		payload = json.loads(class_map_json)
	except json.JSONDecodeError as error:
		raise InvalidRequestError(
			"class_map_json 必须是合法 JSON",
			details={"reason": str(error)},
		) from error

	if not isinstance(payload, dict):
		raise InvalidRequestError("class_map_json 必须是 JSON 对象")

	return {str(key): str(value) for key, value in payload.items()}


def _project_visible(*, principal: AuthenticatedPrincipal, project_id: str) -> bool:
	"""判断当前主体是否可见指定 Project。"""

	if not principal.project_ids:
		return True

	return project_id in principal.project_ids


def _resolve_dataset_import_root(dataset_import: DatasetImport) -> str | None:
	"""解析一次 DatasetImport 对应的本地导入根目录。"""

	if dataset_import.package_path:
		return str(PurePosixPath(dataset_import.package_path).parent)

	if dataset_import.staging_path:
		staging_path = PurePosixPath(dataset_import.staging_path)
		if staging_path.name == "extracted" and staging_path.parent.name == "staging":
			return str(staging_path.parent.parent)
		if staging_path.name == "staging":
			return str(staging_path.parent)
		return str(staging_path.parent)

	return None

