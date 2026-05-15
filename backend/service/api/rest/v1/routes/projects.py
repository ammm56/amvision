"""项目级 summary REST 路由。"""

from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.rest.v1.pagination import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    paginate_sequence,
)
from backend.service.application.errors import (
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.project_summary import ProjectSummaryService, ProjectSummarySnapshot
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.infrastructure.object_store.object_key_layout import (
    build_public_project_object_namespace_patterns,
    is_public_project_object_key,
)
from backend.service.settings import (
    BackendServiceProjectCatalogItemConfig,
    BackendServiceSettings,
)


projects_router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectWorkflowSummaryResponse(BaseModel):
    """描述 Project 下 workflow 聚合摘要响应。"""

    template_total: int = Field(description="模板总数")
    application_total: int = Field(description="流程应用总数")
    preview_run_total: int = Field(description="preview run 总数")
    preview_run_state_counts: dict[str, int] = Field(default_factory=dict, description="preview run 状态计数字典")
    workflow_run_total: int = Field(description="WorkflowRun 总数")
    workflow_run_state_counts: dict[str, int] = Field(default_factory=dict, description="WorkflowRun 状态计数字典")
    app_runtime_total: int = Field(description="WorkflowAppRuntime 总数")
    app_runtime_observed_state_counts: dict[str, int] = Field(
        default_factory=dict,
        description="WorkflowAppRuntime observed_state 计数字典",
    )


class ProjectDeploymentSummaryResponse(BaseModel):
    """描述 Project 下 deployment 聚合摘要响应。"""

    deployment_instance_total: int = Field(description="DeploymentInstance 总数")
    deployment_status_counts: dict[str, int] = Field(default_factory=dict, description="DeploymentInstance status 计数字典")


class ProjectSummaryResponse(BaseModel):
    """描述工作台可直接消费的项目级聚合摘要响应。"""

    project_id: str = Field(description="所属 Project id")
    generated_at: str = Field(description="聚合快照生成时间")
    workflows: ProjectWorkflowSummaryResponse = Field(description="workflow 相关聚合摘要")
    deployments: ProjectDeploymentSummaryResponse = Field(description="deployment 相关聚合摘要")


class ProjectCatalogItemResponse(BaseModel):
    """描述前端可直接消费的 Project 目录项响应。

    字段：
    - project_id：Project id。
    - display_name：展示名称。
    - description：项目说明。
    - metadata：附加元数据。
    - registered_in_catalog：是否来自显式 Project 目录配置。
    - storage_prefix：Project 在本地 ObjectStore 中的固定前缀。
    - summary：可选聚合摘要；仅当请求显式要求时返回。
    """

    project_id: str = Field(description="Project id")
    display_name: str = Field(description="展示名称")
    description: str | None = Field(default=None, description="项目说明")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
    registered_in_catalog: bool = Field(description="是否来自显式 Project 目录配置")
    storage_prefix: str = Field(description="Project 对应的本地 ObjectStore 前缀")
    summary: ProjectSummaryResponse | None = Field(default=None, description="可选聚合摘要")


class ProjectObjectMetadataResponse(BaseModel):
    """描述 Project 内对象文件的读取元数据。

    字段：
    - project_id：所属 Project id。
    - object_key：本地 ObjectStore 相对路径。
    - file_name：文件名。
    - media_type：推断出的媒体类型。
    - size_bytes：文件字节大小。
    - last_modified_at：最近修改时间。
    - content_url：内联读取 URL。
    - download_url：下载 URL。
    """

    project_id: str = Field(description="所属 Project id")
    object_key: str = Field(description="本地 ObjectStore 相对路径")
    file_name: str = Field(description="文件名")
    media_type: str = Field(description="推断出的媒体类型")
    size_bytes: int = Field(description="文件字节大小")
    last_modified_at: str = Field(description="最近修改时间")
    content_url: str = Field(description="内联读取 URL")
    download_url: str = Field(description="下载 URL")


@projects_router.get("", response_model=list[ProjectCatalogItemResponse])
def list_projects(
    request: Request,
    response: Response,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:read", "models:read")),
    ],
    include_summary: Annotated[
        bool,
        Query(description="是否内联返回每个 Project 的 summary"),
    ] = False,
    offset: Annotated[int, Query(ge=0, description="结果偏移量")] = 0,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_LIST_LIMIT, description="最大返回数量"),
    ] = DEFAULT_LIST_LIMIT,
) -> list[ProjectCatalogItemResponse]:
    """列出当前主体可见的 Project 目录项。"""

    project_items = []
    for project_id in _list_visible_project_ids(request=request, principal=principal):
        project_items.append(
            _build_project_catalog_item_response(
                request=request,
                project_id=project_id,
                include_summary=include_summary,
            )
        )
    return paginate_sequence(project_items, response=response, offset=offset, limit=limit)


@projects_router.get("/{project_id}", response_model=ProjectCatalogItemResponse)
def get_project_detail(
    project_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:read", "models:read")),
    ],
) -> ProjectCatalogItemResponse:
    """读取一个 Project 的目录信息和当前 summary。"""

    _ensure_project_known_and_visible(
        request=request,
        principal=principal,
        project_id=project_id,
    )
    return _build_project_catalog_item_response(
        request=request,
        project_id=project_id,
        include_summary=True,
    )


@projects_router.get(
    "/{project_id}/summary",
    response_model=ProjectSummaryResponse,
)
def get_project_summary(
    project_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read", "models:read"))],
) -> ProjectSummaryResponse:
    """读取一个 Project 当前工作台可用的聚合摘要。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    summary = _build_project_summary_service(request).get_project_summary(project_id)
    return _build_project_summary_response(summary)


@projects_router.get(
    "/{project_id}/files/metadata",
    response_model=ProjectObjectMetadataResponse,
)
def get_project_object_metadata(
    project_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:read", "models:read")),
    ],
    object_key: Annotated[str | None, Query(description="Project 内对象相对路径")] = None,
    storage_uri: Annotated[str | None, Query(description="兼容字段；等价于 object_key")] = None,
) -> ProjectObjectMetadataResponse:
    """返回一个 Project 内对象文件的元数据和稳定读取 URL。"""

    resolved_object_key, file_path = _resolve_project_object_path(
        request=request,
        principal=principal,
        project_id=project_id,
        object_key=object_key,
        storage_uri=storage_uri,
    )
    media_type = _guess_media_type(file_path, object_key=resolved_object_key)
    encoded_object_key = quote(resolved_object_key, safe="")
    content_url = (
        f"/api/v1/projects/{project_id}/files/content?object_key={encoded_object_key}"
    )
    download_url = f"{content_url}&download=true"
    return ProjectObjectMetadataResponse(
        project_id=project_id,
        object_key=resolved_object_key,
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


@projects_router.get("/{project_id}/files/content")
def read_project_object_content(
    project_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:read", "models:read")),
    ],
    object_key: Annotated[str | None, Query(description="Project 内对象相对路径")] = None,
    storage_uri: Annotated[str | None, Query(description="兼容字段；等价于 object_key")] = None,
    download: Annotated[bool, Query(description="是否按附件下载")] = False,
) -> FileResponse:
    """读取一个 Project 内对象文件内容，适用于图片预览和结果文件下载。"""

    resolved_object_key, file_path = _resolve_project_object_path(
        request=request,
        principal=principal,
        project_id=project_id,
        object_key=object_key,
        storage_uri=storage_uri,
    )
    media_type = _guess_media_type(file_path, object_key=resolved_object_key)
    filename = file_path.name if download else None
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
    )


def _build_project_summary_service(request: Request) -> ProjectSummaryService:
    """基于 application.state 构建 ProjectSummaryService。"""

    return ProjectSummaryService(
        session_factory=_require_session_factory(request),
        dataset_storage=_require_dataset_storage(request),
    )


def _require_backend_service_settings(request: Request) -> BackendServiceSettings:
    """从 application.state 中读取 BackendServiceSettings。"""

    settings = getattr(request.app.state, "backend_service_settings", None)
    if not isinstance(settings, BackendServiceSettings):
        raise ServiceConfigurationError("当前服务尚未完成 backend_service_settings 装配")
    return settings


def _require_session_factory(request: Request) -> SessionFactory:
    """从 application.state 中读取 SessionFactory。"""

    session_factory = getattr(request.app.state, "session_factory", None)
    if not isinstance(session_factory, SessionFactory):
        raise ServiceConfigurationError("当前服务尚未完成 session_factory 装配")
    return session_factory


def _require_dataset_storage(request: Request) -> LocalDatasetStorage:
    """从 application.state 中读取 LocalDatasetStorage。"""

    dataset_storage = getattr(request.app.state, "dataset_storage", None)
    if not isinstance(dataset_storage, LocalDatasetStorage):
        raise ServiceConfigurationError("当前服务尚未完成 dataset_storage 装配")
    return dataset_storage


def _ensure_project_visible(*, principal: AuthenticatedPrincipal, project_id: str) -> None:
    """校验当前主体是否可访问指定 Project。"""

    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": project_id},
        )


def _ensure_project_known_and_visible(
    *,
    request: Request,
    principal: AuthenticatedPrincipal,
    project_id: str,
) -> None:
    """校验指定 Project 同时满足可见性和最小可发现性要求。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    if principal.project_ids and project_id in principal.project_ids:
        return
    if project_id in set(_list_visible_project_ids(request=request, principal=principal)):
        return
    raise ResourceNotFoundError(
        "请求的 Project 不存在",
        details={"project_id": project_id},
    )


def _list_visible_project_ids(
    *,
    request: Request,
    principal: AuthenticatedPrincipal,
) -> tuple[str, ...]:
    """列出当前主体可见的 Project id 列表。"""

    settings = _require_backend_service_settings(request)
    if principal.project_ids:
        return tuple(dict.fromkeys(principal.project_ids))

    configured_project_ids = [
        item.project_id.strip()
        for item in settings.projects.items
        if item.project_id.strip()
    ]
    discovered_project_ids = _discover_storage_project_ids(_require_dataset_storage(request))
    visible_ids = sorted(set(configured_project_ids).union(discovered_project_ids))
    return tuple(visible_ids)


def _discover_storage_project_ids(dataset_storage: LocalDatasetStorage) -> tuple[str, ...]:
    """从本地 ObjectStore 目录发现已存在的 Project id。"""

    projects_dir = dataset_storage.resolve("projects")
    if not projects_dir.exists() or not projects_dir.is_dir():
        return ()
    return tuple(
        sorted(
            child.name
            for child in projects_dir.iterdir()
            if child.is_dir()
        )
    )


def _build_project_catalog_item_response(
    *,
    request: Request,
    project_id: str,
    include_summary: bool,
) -> ProjectCatalogItemResponse:
    """把 Project 目录配置和运行时 summary 组装为公开响应。"""

    catalog_item = _find_project_catalog_item(request=request, project_id=project_id)
    summary = None
    if include_summary:
        summary = _build_project_summary_response(
            _build_project_summary_service(request).get_project_summary(project_id)
        )
    return ProjectCatalogItemResponse(
        project_id=project_id,
        display_name=(catalog_item.display_name if catalog_item and catalog_item.display_name else project_id),
        description=catalog_item.description if catalog_item is not None else None,
        metadata=dict(catalog_item.metadata) if catalog_item is not None else {},
        registered_in_catalog=catalog_item is not None,
        storage_prefix=f"projects/{project_id}",
        summary=summary,
    )


def _find_project_catalog_item(
    *,
    request: Request,
    project_id: str,
) -> BackendServiceProjectCatalogItemConfig | None:
    """在当前配置中查找一个 Project 目录项。"""

    for item in _require_backend_service_settings(request).projects.items:
        if item.project_id == project_id:
            return item
    return None


def _resolve_project_object_path(
    *,
    request: Request,
    principal: AuthenticatedPrincipal,
    project_id: str,
    object_key: str | None,
    storage_uri: str | None,
) -> tuple[str, Path]:
    """解析并校验一个 Project 内对象文件路径。"""

    _ensure_project_known_and_visible(
        request=request,
        principal=principal,
        project_id=project_id,
    )
    resolved_object_key = _resolve_requested_object_key(
        object_key=object_key,
        storage_uri=storage_uri,
    )
    if not is_public_project_object_key(project_id=project_id, object_key=resolved_object_key):
        raise InvalidRequestError(
            "当前接口只允许读取 Project 公开文件命名空间中的对象文件",
            details={
                "project_id": project_id,
                "object_key": resolved_object_key,
                "allowed_namespaces": build_public_project_object_namespace_patterns(project_id=project_id),
            },
        )
    file_path = _require_dataset_storage(request).resolve(resolved_object_key)
    if not file_path.is_file():
        raise ResourceNotFoundError(
            "请求的对象文件不存在",
            details={"project_id": project_id, "object_key": resolved_object_key},
        )
    return resolved_object_key, file_path


def _resolve_requested_object_key(
    *,
    object_key: str | None,
    storage_uri: str | None,
) -> str:
    """统一解析 object_key 和兼容 storage_uri 参数。"""

    candidates = [
        candidate.strip()
        for candidate in (object_key, storage_uri)
        if candidate is not None and candidate.strip()
    ]
    if not candidates:
        raise InvalidRequestError("object_key 或 storage_uri 至少需要提供一个")
    if len(set(candidates)) > 1:
        raise InvalidRequestError(
            "object_key 和 storage_uri 不能同时提供不同的值",
            details={"object_key": object_key, "storage_uri": storage_uri},
        )
    return candidates[0]


def _guess_media_type(file_path: Path, *, object_key: str) -> str:
    """按文件名和 object key 猜测响应媒体类型。"""

    guessed_media_type, _ = mimetypes.guess_type(object_key)
    if guessed_media_type is not None:
        return guessed_media_type
    guessed_media_type, _ = mimetypes.guess_type(file_path.name)
    if guessed_media_type is not None:
        return guessed_media_type
    return "application/octet-stream"


def _build_project_summary_response(summary: ProjectSummarySnapshot) -> ProjectSummaryResponse:
    """把项目级聚合快照转换为公开响应。"""

    return ProjectSummaryResponse(
        project_id=summary.project_id,
        generated_at=summary.generated_at,
        workflows=ProjectWorkflowSummaryResponse(
            template_total=summary.workflows.template_total,
            application_total=summary.workflows.application_total,
            preview_run_total=summary.workflows.preview_run_total,
            preview_run_state_counts=dict(summary.workflows.preview_run_state_counts),
            workflow_run_total=summary.workflows.workflow_run_total,
            workflow_run_state_counts=dict(summary.workflows.workflow_run_state_counts),
            app_runtime_total=summary.workflows.app_runtime_total,
            app_runtime_observed_state_counts=dict(summary.workflows.app_runtime_observed_state_counts),
        ),
        deployments=ProjectDeploymentSummaryResponse(
            deployment_instance_total=summary.deployments.deployment_instance_total,
            deployment_status_counts=dict(summary.deployments.deployment_status_counts),
        ),
    )