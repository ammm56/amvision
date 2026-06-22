"""模型路由响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlatformBaseModelFileResponse(BaseModel):
    """描述平台基础模型详情中的文件条目。

    字段：
    - file_id：文件记录 id。
    - project_id：所属 Project id；平台基础模型文件时为空。
    - scope_kind：文件所属模型作用域类型。
    - model_id：所属 Model id。
    - model_version_id：所属 ModelVersion id。
    - model_build_id：所属 ModelBuild id。
    - file_type：文件类型。
    - logical_name：文件逻辑名。
    - storage_uri：文件存储 URI。
    - metadata：附加元数据。
    """

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
    """描述平台基础模型列表中的版本摘要。

    字段：
    - model_version_id：ModelVersion id。
    - source_kind：版本来源类型。
    - dataset_version_id：关联 DatasetVersion id。
    - training_task_id：关联训练任务 id。
    - parent_version_id：父 ModelVersion id。
    - file_ids：关联文件 id 列表。
    - metadata：附加元数据。
    - checkpoint_file_id：checkpoint 文件 id。
    - checkpoint_storage_uri：checkpoint 存储 URI。
    - catalog_manifest_object_key：预训练目录 manifest object key。
    """

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
    """描述平台基础模型详情中的版本条目。

    字段：
    - files：版本文件列表。
    """

    files: list[PlatformBaseModelFileResponse] = Field(default_factory=list, description="版本文件列表")


class PlatformBaseModelBuildResponse(BaseModel):
    """描述平台基础模型详情中的构建条目。

    字段：
    - model_build_id：ModelBuild id。
    - source_model_version_id：来源 ModelVersion id。
    - build_format：构建格式。
    - runtime_profile_id：目标 RuntimeProfile id。
    - conversion_task_id：来源转换任务 id。
    - file_ids：关联文件 id 列表。
    - metadata：附加元数据。
    - files：构建文件列表。
    """

    model_build_id: str = Field(description="ModelBuild id")
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    build_format: str = Field(description="构建格式")
    runtime_profile_id: str | None = Field(default=None, description="目标 RuntimeProfile id")
    conversion_task_id: str | None = Field(default=None, description="来源转换任务 id")
    file_ids: tuple[str, ...] = Field(default_factory=tuple, description="关联文件 id 列表")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
    files: list[PlatformBaseModelFileResponse] = Field(default_factory=list, description="构建文件列表")


class PlatformBaseModelSummaryResponse(BaseModel):
    """描述平台基础模型列表项。

    字段：
    - model_id：Model id。
    - project_id：所属 Project id；平台基础模型时为空。
    - scope_kind：模型作用域类型。
    - model_name：模型名。
    - model_type：模型类型名称。
    - task_type：任务类型。
    - model_scale：模型 scale。
    - labels_file_id：标签文件 id。
    - metadata：附加元数据。
    - version_count：关联 ModelVersion 数量。
    - build_count：关联 ModelBuild 数量。
    - available_versions：可用于 warm start 的版本摘要列表。
    """

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
    """描述平台基础模型详情响应。

    字段：
    - versions：完整版本列表。
    - builds：完整构建列表。
    """

    versions: list[PlatformBaseModelVersionDetailResponse] = Field(default_factory=list, description="完整版本列表")
    builds: list[PlatformBaseModelBuildResponse] = Field(default_factory=list, description="完整构建列表")
