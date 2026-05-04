"""模型 REST 路由分组。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.application.errors import ResourceNotFoundError
from backend.service.application.models.yolox_model_service import (
    PlatformBaseModelBuildView,
    PlatformBaseModelDetailView,
    PlatformBaseModelFileView,
    PlatformBaseModelSummaryView,
    PlatformBaseModelVersionDetailView,
    PlatformBaseModelVersionSummaryView,
    SqlAlchemyYoloXModelService,
)
from backend.service.infrastructure.db.session import SessionFactory


models_router = APIRouter(prefix="/models", tags=["models"])


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