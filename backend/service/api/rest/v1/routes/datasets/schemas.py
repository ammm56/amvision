"""数据集 API 请求与响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DatasetImportSubmissionResponse(BaseModel):
	"""描述数据集导入提交接口响应。"""

	dataset_import_id: str = Field(description="导入记录 id")
	task_id: str | None = Field(default=None, description="关联的任务 id")
	status: str = Field(description="导入状态")
	upload_state: str = Field(description="上传状态")
	processing_state: str = Field(description="处理状态")
	package_size: int = Field(description="已保存的 zip 包大小")
	package_path: str = Field(description="原始 zip 包相对路径")
	staging_path: str = Field(description="解压目录相对路径")
	queue_name: str = Field(description="提交到的队列名称")
	queue_task_id: str = Field(description="队列任务 id")


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
	task_id: str | None = Field(default=None, description="关联的任务 id")
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
	package_size: int | None = Field(description="原始 zip 包大小")
	upload_state: str | None = Field(description="上传状态")
	processing_state: str = Field(description="处理状态")
	queue_task_id: str | None = Field(description="关联的队列任务 id")
	validation_status: str | None = Field(description="校验报告中的状态")
	error_message: str | None = Field(description="失败时的错误消息")


class DatasetImportDetailResponse(BaseModel):
	"""描述 DatasetImport 查询接口返回的完整记录。"""

	dataset_import_id: str = Field(description="导入记录 id")
	task_id: str | None = Field(default=None, description="关联的任务 id")
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
	package_size: int | None = Field(description="原始 zip 包大小")
	upload_state: str | None = Field(description="上传状态")
	processing_state: str = Field(description="处理状态")
	queue_task_id: str | None = Field(description="关联的队列任务 id")
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
	package_object_key: str | None = Field(default=None, description="导出下载包 object key")
	package_file_name: str | None = Field(default=None, description="导出下载包文件名")
	package_size: int | None = Field(default=None, description="导出下载包大小")
	packaged_at: str | None = Field(default=None, description="最近一次打包时间")
	error_message: str | None = Field(default=None, description="失败时的错误消息")
	metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class DatasetExportDetailResponse(DatasetExportSummaryResponse):
	"""描述 DatasetExport 查询接口返回的完整记录。"""


class DatasetExportPackageResponse(BaseModel):
	"""描述 DatasetExport 下载包接口响应。"""

	dataset_export_id: str = Field(description="导出记录 id")
	export_path: str = Field(description="导出根目录 object key")
	manifest_object_key: str = Field(description="导出 manifest object key")
	package_object_key: str = Field(description="导出下载包 object key")
	package_file_name: str = Field(description="导出下载包文件名")
	package_size: int = Field(description="导出下载包大小")
	packaged_at: str = Field(description="最近一次打包时间")


class DatasetExportFormatItemResponse(BaseModel):
	"""描述单个已实现数据集导出格式的公开规则项。"""

	format_id: str = Field(description="导出格式 id")


class DatasetExportFormatCatalogResponse(BaseModel):
	"""描述数据集导出格式公开能力规则。"""

	implemented_formats: list[str] = Field(default_factory=list, description="当前已实现并可用的格式")
	default_format: str = Field(description="默认导出格式")
	format_types_by_task_type: dict[str, list[str]] = Field(
		default_factory=dict,
		description="按 task_type 列出的已实现导出格式",
	)
	items: list[DatasetExportFormatItemResponse] = Field(default_factory=list, description="已实现格式列表")
