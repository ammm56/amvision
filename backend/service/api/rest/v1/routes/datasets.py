"""数据集 REST 路由分组。"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory, get_unit_of_work
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.datasets.dataset_import import (
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
	DatasetFormatType,
	DatasetImport,
	DatasetImportRequestedSplitStrategy,
)
from backend.service.domain.datasets.dataset_version import DatasetTaskType, DatasetVersion
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


class DatasetVersionRelationResponse(BaseModel):
	"""描述 DatasetImport 关联的 DatasetVersion 摘要。"""

	dataset_version_id: str = Field(description="关联的 DatasetVersion id")
	dataset_id: str = Field(description="所属 Dataset id")
	project_id: str = Field(description="所属 Project id")
	task_type: str = Field(description="任务类型")
	sample_count: int = Field(description="样本总数")
	category_count: int = Field(description="类别总数")
	split_names: tuple[str, ...] = Field(description="版本包含的 split 列表")
	metadata: dict[str, object] = Field(description="版本元数据")


class DatasetImportFailureResponse(BaseModel):
	"""描述导入失败时的结构化错误对象。"""

	code: str | None = Field(default=None, description="稳定错误码")
	message: str | None = Field(default=None, description="错误消息")
	details: dict[str, object] = Field(default_factory=dict, description="附加错误细节")


class DatasetImportDetectedProfileResponse(BaseModel):
	"""描述导入阶段识别出的格式签名。"""

	detected_candidates: tuple[str, ...] = Field(default_factory=tuple, description="识别到的候选格式列表")
	format_type: str | None = Field(default=None, description="最终识别出的格式类型")
	task_type: str | None = Field(default=None, description="最终识别出的任务类型")
	manifest_files: tuple[str, ...] = Field(default_factory=tuple, description="识别到的 manifest 文件列表")
	annotation_root: str | None = Field(default=None, description="识别出的标注根目录")
	image_root: str | None = Field(default=None, description="识别出的图片根目录")
	split_names: tuple[str, ...] = Field(default_factory=tuple, description="识别出的 split 列表")
	split_counts: dict[str, int] = Field(default_factory=dict, description="各 split 的样本数量")


class DatasetImportValidationReportResponse(BaseModel):
	"""描述导入阶段输出的结构化校验报告。"""

	status: str | None = Field(default=None, description="校验状态")
	format_type: str | None = Field(default=None, description="校验对应的数据集格式")
	task_type: str | None = Field(default=None, description="校验对应的任务类型")
	category_count: int | None = Field(default=None, description="校验得到的类别总数")
	sample_count: int | None = Field(default=None, description="校验得到的样本总数")
	split_counts: dict[str, int] = Field(default_factory=dict, description="各 split 的样本数量")
	warnings: list[dict[str, object]] = Field(default_factory=list, description="校验警告列表")
	errors: list[dict[str, object]] = Field(default_factory=list, description="校验错误列表")
	error: DatasetImportFailureResponse | None = Field(default=None, description="失败时的错误信息")


class DatasetImportSummaryResponse(BaseModel):
	"""描述 DatasetImport 列表中的单条记录摘要。"""

	dataset_import_id: str = Field(description="导入记录 id")
	dataset_id: str = Field(description="所属 Dataset id")
	project_id: str = Field(description="所属 Project id")
	format_type: str | None = Field(description="导入格式类型")
	task_type: str = Field(description="任务类型")
	status: str = Field(description="导入状态")
	created_at: str = Field(description="导入记录创建时间")
	dataset_version_id: str | None = Field(description="生成的 DatasetVersion id")
	package_path: str = Field(description="原始 zip 包相对路径")
	staging_path: str = Field(description="解压目录相对路径")
	version_path: str | None = Field(description="版本目录相对路径")
	validation_status: str | None = Field(description="校验报告中的状态")
	error_message: str | None = Field(description="失败时的错误消息")


class DatasetImportDetailResponse(BaseModel):
	"""描述 DatasetImport 查询接口返回的完整记录。"""

	dataset_import_id: str = Field(description="导入记录 id")
	dataset_id: str = Field(description="所属 Dataset id")
	project_id: str = Field(description="所属 Project id")
	format_type: str | None = Field(description="导入格式类型")
	task_type: str = Field(description="任务类型")
	status: str = Field(description="导入状态")
	created_at: str = Field(description="导入记录创建时间")
	dataset_version_id: str | None = Field(description="生成的 DatasetVersion id")
	package_path: str = Field(description="原始 zip 包相对路径")
	staging_path: str = Field(description="解压目录相对路径")
	version_path: str | None = Field(description="版本目录相对路径")
	image_root: str | None = Field(description="识别出的图片根路径")
	annotation_root: str | None = Field(description="识别出的标注根路径")
	manifest_file: str | None = Field(description="识别出的 manifest 文件路径")
	split_strategy: str | None = Field(description="导入使用的 split 策略")
	class_map: dict[str, str] = Field(description="类别映射")
	detected_profile: DatasetImportDetectedProfileResponse = Field(description="格式识别结果")
	validation_report: DatasetImportValidationReportResponse = Field(description="结构化校验报告")
	error_message: str | None = Field(description="失败时的错误消息")
	metadata: dict[str, object] = Field(description="附加元数据")
	dataset_version: DatasetVersionRelationResponse | None = Field(
		default=None,
		description="关联的 DatasetVersion 摘要",
	)


@datasets_router.post("/imports", response_model=DatasetImportResponse, status_code=201)
async def import_dataset_zip(
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	project_id: Annotated[str, Form()],
	dataset_id: Annotated[str, Form()],
	package: Annotated[UploadFile, File()],
	format_type: Annotated[DatasetFormatType | None, Form()] = None,
	task_type: Annotated[DatasetTaskType, Form()] = "detection",
	split_strategy: Annotated[DatasetImportRequestedSplitStrategy | None, Form()] = None,
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
	service = SqlAlchemyDatasetImportService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
	)
	import_result = service.import_dataset(
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


@datasets_router.get(
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


@datasets_router.get(
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


def _build_dataset_import_summary(dataset_import: DatasetImport) -> DatasetImportSummaryResponse:
	"""把 DatasetImport 转成列表摘要响应。"""

	return DatasetImportSummaryResponse(
		dataset_import_id=dataset_import.dataset_import_id,
		dataset_id=dataset_import.dataset_id,
		project_id=dataset_import.project_id,
		format_type=dataset_import.format_type,
		task_type=dataset_import.task_type,
		status=dataset_import.status,
		created_at=dataset_import.created_at,
		dataset_version_id=dataset_import.dataset_version_id,
		package_path=dataset_import.package_path,
		staging_path=dataset_import.staging_path,
		version_path=dataset_import.version_path,
		validation_status=_read_validation_status(dataset_import.validation_report),
		error_message=dataset_import.error_message,
	)


def _build_dataset_import_detail(
	*,
	dataset_import: DatasetImport,
	dataset_version: DatasetVersion | None,
) -> DatasetImportDetailResponse:
	"""把 DatasetImport 和关联版本转换为详情响应。"""

	return DatasetImportDetailResponse(
		dataset_import_id=dataset_import.dataset_import_id,
		dataset_id=dataset_import.dataset_id,
		project_id=dataset_import.project_id,
		format_type=dataset_import.format_type,
		task_type=dataset_import.task_type,
		status=dataset_import.status,
		created_at=dataset_import.created_at,
		dataset_version_id=dataset_import.dataset_version_id,
		package_path=dataset_import.package_path,
		staging_path=dataset_import.staging_path,
		version_path=dataset_import.version_path,
		image_root=dataset_import.image_root,
		annotation_root=dataset_import.annotation_root,
		manifest_file=dataset_import.manifest_file,
		split_strategy=dataset_import.split_strategy,
		class_map=dict(dataset_import.class_map),
		detected_profile=_build_detected_profile_response(dataset_import.detected_profile),
		validation_report=_build_validation_report_response(dataset_import.validation_report),
		error_message=dataset_import.error_message,
		metadata=dict(dataset_import.metadata),
		dataset_version=_build_dataset_version_relation(dataset_version),
	)


def _build_dataset_version_relation(
	dataset_version: DatasetVersion | None,
) -> DatasetVersionRelationResponse | None:
	"""把 DatasetVersion 转成关联摘要响应。"""

	if dataset_version is None:
		return None

	return DatasetVersionRelationResponse(
		dataset_version_id=dataset_version.dataset_version_id,
		dataset_id=dataset_version.dataset_id,
		project_id=dataset_version.project_id,
		task_type=dataset_version.task_type,
		sample_count=len(dataset_version.samples),
		category_count=len(dataset_version.categories),
		split_names=_collect_split_names(dataset_version),
		metadata=dict(dataset_version.metadata),
	)


def _collect_split_names(dataset_version: DatasetVersion) -> tuple[str, ...]:
	"""按固定顺序收集 DatasetVersion 中出现的 split 名称。"""

	present_splits = {sample.split for sample in dataset_version.samples}
	return tuple(split_name for split_name in ("train", "val", "test") if split_name in present_splits)


def _read_validation_status(validation_report: dict[str, object]) -> str | None:
	"""从校验报告里读取状态字段。"""

	status = validation_report.get("status")
	if isinstance(status, str):
		return status

	return None


def _build_detected_profile_response(
	profile: dict[str, object],
) -> DatasetImportDetectedProfileResponse:
	"""把导入记录中的 profile 字典转换为显式响应模型。"""

	manifest_files = profile.get("manifest_files", ())
	split_names = profile.get("split_names", ())
	split_counts = profile.get("split_counts", {})
	detected_candidates = profile.get("detected_candidates", ())

	return DatasetImportDetectedProfileResponse(
		detected_candidates=tuple(
			str(candidate) for candidate in detected_candidates if isinstance(candidate, str)
		),
		format_type=_read_optional_str(profile, "format_type"),
		task_type=_read_optional_str(profile, "task_type"),
		manifest_files=tuple(
			str(manifest_file) for manifest_file in manifest_files if isinstance(manifest_file, str)
		),
		annotation_root=_read_optional_str(profile, "annotation_root"),
		image_root=_read_optional_str(profile, "image_root"),
		split_names=tuple(
			str(split_name) for split_name in split_names if isinstance(split_name, str)
		),
		split_counts={
			str(split_name): int(sample_count)
			for split_name, sample_count in split_counts.items()
			if isinstance(split_name, str)
		},
	)


def _build_validation_report_response(
	report: dict[str, object],
) -> DatasetImportValidationReportResponse:
	"""把导入记录中的校验报告字典转换为显式响应模型。"""

	error_payload = report.get("error")
	split_counts = report.get("split_counts", {})
	warnings = report.get("warnings", [])
	errors = report.get("errors", [])

	return DatasetImportValidationReportResponse(
		status=_read_optional_str(report, "status"),
		format_type=_read_optional_str(report, "format_type"),
		task_type=_read_optional_str(report, "task_type"),
		category_count=_read_optional_int(report, "category_count"),
		sample_count=_read_optional_int(report, "sample_count"),
		split_counts={
			str(split_name): int(sample_count)
			for split_name, sample_count in split_counts.items()
			if isinstance(split_name, str)
		},
		warnings=[warning for warning in warnings if isinstance(warning, dict)],
		errors=[error for error in errors if isinstance(error, dict)],
		error=_build_failure_response(error_payload),
	)


def _build_failure_response(payload: object) -> DatasetImportFailureResponse | None:
	"""把失败信息字典转换为显式错误模型。"""

	if not isinstance(payload, dict):
		return None

	return DatasetImportFailureResponse(
		code=_read_optional_str(payload, "code"),
		message=_read_optional_str(payload, "message"),
		details={
			str(key): value
			for key, value in payload.items()
			if key not in {"code", "message"}
		},
	)


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
	"""从字典中读取可选字符串字段。"""

	value = payload.get(key)
	if isinstance(value, str):
		return value

	return None


def _read_optional_int(payload: dict[str, object], key: str) -> int | None:
	"""从字典中读取可选整数字段。"""

	value = payload.get(key)
	if isinstance(value, int):
		return value
	if isinstance(value, float):
		return int(value)

	return None