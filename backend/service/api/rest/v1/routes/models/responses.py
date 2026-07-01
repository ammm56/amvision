"""模型路由响应构造函数。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.models.schemas import (
    DeploymentSourceModelDetailResponse,
    DeploymentSourceModelSummaryResponse,
    PlatformBaseModelBuildResponse,
    PlatformBaseModelDetailResponse,
    PlatformBaseModelFileResponse,
    PlatformBaseModelSummaryResponse,
    PlatformBaseModelVersionDetailResponse,
    PlatformBaseModelVersionSummaryResponse,
)
from backend.service.application.models.registry.model_service import (
    PlatformBaseModelBuildView,
    PlatformBaseModelDetailView,
    PlatformBaseModelFileView,
    PlatformBaseModelSummaryView,
    PlatformBaseModelVersionDetailView,
    PlatformBaseModelVersionSummaryView,
)


def build_platform_base_model_summary_response(
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
            build_platform_base_model_version_summary_response(version)
            for version in model.available_versions
        ],
    )


def build_platform_base_model_detail_response(
    model: PlatformBaseModelDetailView,
) -> PlatformBaseModelDetailResponse:
    """把平台基础模型详情视图转换为响应对象。"""

    return PlatformBaseModelDetailResponse(
        **build_platform_base_model_summary_response(model).model_dump(),
        versions=[build_platform_base_model_version_detail_response(version) for version in model.versions],
        builds=[build_platform_base_model_build_response(build) for build in model.builds],
    )


def build_deployment_source_model_summary_response(
    model: PlatformBaseModelSummaryView,
) -> DeploymentSourceModelSummaryResponse:
    """把部署来源模型摘要视图转换为响应对象。"""

    return DeploymentSourceModelSummaryResponse(
        **build_platform_base_model_summary_response(model).model_dump(),
    )


def build_deployment_source_model_detail_response(
    model: PlatformBaseModelDetailView,
) -> DeploymentSourceModelDetailResponse:
    """把部署来源模型详情视图转换为响应对象。"""

    return DeploymentSourceModelDetailResponse(
        **build_platform_base_model_detail_response(model).model_dump(),
    )


def build_platform_base_model_version_summary_response(
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


def build_platform_base_model_version_detail_response(
    version: PlatformBaseModelVersionDetailView,
) -> PlatformBaseModelVersionDetailResponse:
    """把平台基础模型版本详情视图转换为响应对象。"""

    return PlatformBaseModelVersionDetailResponse(
        **build_platform_base_model_version_summary_response(version).model_dump(),
        files=[build_platform_base_model_file_response(model_file) for model_file in version.files],
    )


def build_platform_base_model_build_response(
    build: PlatformBaseModelBuildView,
) -> PlatformBaseModelBuildResponse:
    """把平台基础模型构建视图转换为响应对象。"""

    return PlatformBaseModelBuildResponse(
        model_build_id=build.model_build_id,
        source_model_version_id=build.source_model_version_id,
        build_format=build.build_format,
        runtime_backend=build.runtime_backend,
        runtime_precision=build.runtime_precision,
        runtime_profile_id=build.runtime_profile_id,
        conversion_task_id=build.conversion_task_id,
        file_ids=build.file_ids,
        metadata=dict(build.metadata),
        files=[build_platform_base_model_file_response(model_file) for model_file in build.files],
    )


def build_platform_base_model_file_response(
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
