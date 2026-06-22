"""数据集 API 响应组装。"""

from __future__ import annotations

from backend.contracts.datasets.exports.dataset_formats import (
	IMPLEMENTED_DATASET_EXPORT_FORMATS,
	IMPLEMENTED_DATASET_EXPORT_FORMAT_TYPES_BY_TASK_TYPE,
)
from backend.service.application.datasets.exports.delivery import DatasetExportPackage
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.datasets.dataset_import import DatasetImport
from backend.service.domain.datasets.dataset_version import DatasetVersion

from .schemas import (
	DatasetExportDetailResponse,
	DatasetExportFormatCatalogResponse,
	DatasetExportFormatItemResponse,
	DatasetExportPackageResponse,
	DatasetImportDetectedProfileResponse,
	DatasetImportDetailResponse,
	DatasetImportFailureResponse,
	DatasetImportSummaryResponse,
	DatasetImportValidationReportResponse,
	DatasetVersionRelationResponse,
)


def _build_dataset_import_summary(dataset_import: DatasetImport) -> DatasetImportSummaryResponse:
	"""把 DatasetImport 转成列表摘要响应。"""

	return DatasetImportSummaryResponse(
		dataset_import_id=dataset_import.dataset_import_id,
		task_id=_read_optional_str(dataset_import.metadata, "task_id"),
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
		package_size=_read_optional_int(dataset_import.metadata, "package_size"),
		upload_state=_read_optional_str(dataset_import.metadata, "upload_state"),
		processing_state=_derive_processing_state(dataset_import),
		queue_task_id=_read_optional_str(dataset_import.metadata, "queue_task_id"),
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
		task_id=_read_optional_str(dataset_import.metadata, "task_id"),
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
		package_size=_read_optional_int(dataset_import.metadata, "package_size"),
		upload_state=_read_optional_str(dataset_import.metadata, "upload_state"),
		processing_state=_derive_processing_state(dataset_import),
		queue_task_id=_read_optional_str(dataset_import.metadata, "queue_task_id"),
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


def _derive_processing_state(dataset_import: DatasetImport) -> str:
	"""根据 DatasetImport 当前状态推导处理状态。"""

	if dataset_import.status == "received":
		return "queued"
	if dataset_import.status in {"extracted", "validated"}:
		return "running"
	if dataset_import.status == "completed":
		return "completed"
	if dataset_import.status == "failed":
		return "failed"

	return dataset_import.status


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
		package_object_key=_read_optional_str(dataset_export.metadata, "package_object_key"),
		package_file_name=_read_optional_str(dataset_export.metadata, "package_file_name"),
		package_size=_read_optional_int(dataset_export.metadata, "package_size"),
		packaged_at=_read_optional_str(dataset_export.metadata, "packaged_at"),
		error_message=dataset_export.error_message,
		metadata=dict(dataset_export.metadata),
	)


def _build_dataset_export_package_response(
	package: DatasetExportPackage,
) -> DatasetExportPackageResponse:
	"""把 DatasetExportPackage 转成显式响应模型。"""

	return DatasetExportPackageResponse(
		dataset_export_id=package.dataset_export_id,
		export_path=package.export_path,
		manifest_object_key=package.manifest_object_key,
		package_object_key=package.package_object_key,
		package_file_name=package.package_file_name,
		package_size=package.package_size,
		packaged_at=package.packaged_at,
	)


def _build_dataset_export_format_catalog_response() -> DatasetExportFormatCatalogResponse:
	"""构造稳定的数据集导出格式能力规则响应。"""

	return DatasetExportFormatCatalogResponse(
		implemented_formats=list(IMPLEMENTED_DATASET_EXPORT_FORMATS),
		default_format=IMPLEMENTED_DATASET_EXPORT_FORMATS[0],
		format_types_by_task_type={
			task_type: list(format_types)
			for task_type, format_types in IMPLEMENTED_DATASET_EXPORT_FORMAT_TYPES_BY_TASK_TYPE.items()
		},
		items=[
			DatasetExportFormatItemResponse(format_id=format_id)
			for format_id in IMPLEMENTED_DATASET_EXPORT_FORMATS
		],
	)
