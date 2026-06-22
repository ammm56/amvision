"""Project REST 响应构造。"""

from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import Request

from backend.service.application.project_summary import ProjectSummarySnapshot
from backend.service.infrastructure.object_store.object_key_layout import (
    build_public_project_file_id,
)
from backend.service.settings import BackendServiceProjectCatalogItemConfig
from backend.service.api.rest.v1.routes.projects.schemas import (
    ProjectCatalogItemResponse,
    ProjectDatasetInventoryResponse,
    ProjectDeploymentSummaryResponse,
    ProjectObjectMetadataResponse,
    ProjectSource,
    ProjectStatusSummaryResponse,
    ProjectSummaryResponse,
    ProjectWorkflowSummaryResponse,
)
from backend.service.api.rest.v1.routes.projects.services import (
    build_project_summary_service,
    find_project_catalog_item,
    find_project_manifest,
)


def build_project_catalog_item_response(
    *,
    request: Request,
    project_id: str,
    include_summary: bool,
) -> ProjectCatalogItemResponse:
    """把 Project 目录配置和运行时 summary 组装为公开响应。"""

    catalog_item = find_project_catalog_item(request=request, project_id=project_id)
    project_manifest = find_project_manifest(request=request, project_id=project_id)
    summary = None
    if include_summary:
        summary = build_project_summary_response(
            build_project_summary_service(request).get_project_summary(project_id)
        )
    display_name = project_id
    if project_manifest is not None:
        display_name = project_manifest.display_name
    if catalog_item is not None and catalog_item.display_name:
        display_name = catalog_item.display_name

    description = None
    if project_manifest is not None:
        description = project_manifest.description
    if catalog_item is not None and catalog_item.description is not None:
        description = catalog_item.description

    metadata: dict[str, object] = {}
    if project_manifest is not None:
        metadata.update(project_manifest.metadata)
    if catalog_item is not None:
        metadata.update(catalog_item.metadata)
    return ProjectCatalogItemResponse(
        project_id=project_id,
        display_name=display_name,
        description=description,
        metadata=metadata,
        project_source=resolve_project_source(catalog_item=catalog_item),
        storage_prefix=f"projects/{project_id}",
        summary=summary,
    )


def build_project_object_metadata_response(
    *,
    project_id: str,
    object_key: str,
    file_path: Path,
) -> ProjectObjectMetadataResponse:
    """把 Project 公开文件转换为带 file_id 的统一元数据响应。"""

    media_type = guess_media_type(file_path, object_key=object_key)
    encoded_object_key = quote(object_key, safe="")
    content_url = (
        f"/api/v1/projects/{project_id}/files/content?object_key={encoded_object_key}"
    )
    download_url = f"{content_url}&download=true"
    return ProjectObjectMetadataResponse(
        project_id=project_id,
        file_id=build_public_project_file_id(
            project_id=project_id, object_key=object_key
        ),
        object_key=object_key,
        file_name=file_path.name,
        media_type=media_type,
        size_bytes=file_path.stat().st_size,
        last_modified_at=datetime.fromtimestamp(
            file_path.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat(),
        content_url=content_url,
        download_url=download_url,
    )


def build_project_summary_response(
    summary: ProjectSummarySnapshot,
) -> ProjectSummaryResponse:
    """把项目级聚合快照转换为公开响应。"""

    return ProjectSummaryResponse(
        project_id=summary.project_id,
        generated_at=summary.generated_at,
        datasets=ProjectDatasetInventoryResponse(
            dataset_total=summary.datasets.dataset_total,
        ),
        imports=ProjectStatusSummaryResponse(
            total=summary.imports.total,
            status_counts=dict(summary.imports.status_counts),
        ),
        exports=ProjectStatusSummaryResponse(
            total=summary.exports.total,
            status_counts=dict(summary.exports.status_counts),
        ),
        training=ProjectStatusSummaryResponse(
            total=summary.training.total,
            status_counts=dict(summary.training.status_counts),
        ),
        validation=ProjectStatusSummaryResponse(
            total=summary.validation.total,
            status_counts=dict(summary.validation.status_counts),
        ),
        evaluation=ProjectStatusSummaryResponse(
            total=summary.evaluation.total,
            status_counts=dict(summary.evaluation.status_counts),
        ),
        conversion=ProjectStatusSummaryResponse(
            total=summary.conversion.total,
            status_counts=dict(summary.conversion.status_counts),
        ),
        inference=ProjectStatusSummaryResponse(
            total=summary.inference.total,
            status_counts=dict(summary.inference.status_counts),
        ),
        workflows=ProjectWorkflowSummaryResponse(
            template_total=summary.workflows.template_total,
            application_total=summary.workflows.application_total,
            preview_run_total=summary.workflows.preview_run_total,
            preview_run_state_counts=dict(summary.workflows.preview_run_state_counts),
            workflow_run_total=summary.workflows.workflow_run_total,
            workflow_run_state_counts=dict(summary.workflows.workflow_run_state_counts),
            app_runtime_total=summary.workflows.app_runtime_total,
            app_runtime_observed_state_counts=dict(
                summary.workflows.app_runtime_observed_state_counts
            ),
        ),
        deployments=ProjectDeploymentSummaryResponse(
            deployment_instance_total=summary.deployments.deployment_instance_total,
            deployment_status_counts=dict(summary.deployments.deployment_status_counts),
        ),
    )


def resolve_project_source(
    *,
    catalog_item: BackendServiceProjectCatalogItemConfig | None,
) -> ProjectSource:
    """根据 Project 是否来自配置目录返回公开来源值。"""

    return "configured" if catalog_item is not None else "local_disk"


def guess_media_type(file_path: Path, *, object_key: str) -> str:
    """按文件名和 object key 猜测响应媒体类型。"""

    guessed_media_type, _ = mimetypes.guess_type(object_key)
    if guessed_media_type is not None:
        return guessed_media_type
    guessed_media_type, _ = mimetypes.guess_type(file_path.name)
    if guessed_media_type is not None:
        return guessed_media_type
    return "application/octet-stream"

