"""数据集 REST 路由分组。"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.datasets.dataset_import import (
	DatasetImportRequest,
	SqlAlchemyDatasetImportService,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


datasets_router = APIRouter(prefix="/datasets", tags=["datasets"])


class DatasetImportResponse(BaseModel):
	"""描述数据集导入接口响应。"""

	dataset_import_id: str = Field(description="导入记录 id")
	dataset_version_id: str = Field(description="生成的 DatasetVersion id")
	format_type: str = Field(description="最终识别的格式类型")
	task_type: str = Field(description="最终任务类型")
	status: str = Field(description="导入状态")
	sample_count: int = Field(description="样本总数")
	category_count: int = Field(description="类别总数")
	split_names: tuple[str, ...] = Field(description="导入后包含的 split 列表")
	package_path: str = Field(description="原始 zip 包相对路径")
	staging_path: str = Field(description="解压目录相对路径")
	version_path: str = Field(description="版本目录相对路径")


@datasets_router.post("/imports", response_model=DatasetImportResponse, status_code=201)
async def import_dataset_zip(
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	project_id: Annotated[str, Form()],
	dataset_id: Annotated[str, Form()],
	package: Annotated[UploadFile, File()],
	format_type: Annotated[str | None, Form()] = None,
	task_type: Annotated[str, Form()] = "detection",
	split_strategy: Annotated[str | None, Form()] = None,
	class_map_json: Annotated[str | None, Form()] = None,
) -> DatasetImportResponse:
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
	package_bytes = await package.read()
	service = SqlAlchemyDatasetImportService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
	)
	import_result = service.import_dataset(
		DatasetImportRequest(
			project_id=project_id,
			dataset_id=dataset_id,
			package_file_name=package.filename or "dataset.zip",
			package_bytes=package_bytes,
			format_type=format_type,
			task_type=task_type,
			split_strategy=split_strategy,
			class_map=class_map,
			metadata={"principal_id": principal.principal_id},
		)
	)

	dataset_import = import_result.dataset_import
	return DatasetImportResponse(
		dataset_import_id=dataset_import.dataset_import_id,
		dataset_version_id=dataset_import.dataset_version_id or "",
		format_type=dataset_import.format_type or "",
		task_type=dataset_import.task_type,
		status=dataset_import.status,
		sample_count=import_result.sample_count,
		category_count=import_result.category_count,
		split_names=import_result.split_names,
		package_path=dataset_import.package_path,
		staging_path=dataset_import.staging_path,
		version_path=dataset_import.version_path or "",
	)


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