"""项目级 summary REST 路由。"""

from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response, status
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
from backend.service.application.project_bootstrap import (
    LocalProjectBootstrapService,
    ProjectBootstrapRequest,
    ProjectManifest,
)
from backend.service.application.project_summary import ProjectSummaryService, ProjectSummarySnapshot
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.infrastructure.object_store.object_key_layout import (
    build_public_project_file_id,
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


class ProjectDatasetInventoryResponse(BaseModel):
    """描述 Project 下的数据集目录库存摘要。"""

    dataset_total: int = Field(description="Project datasets 目录下的数据集总数")


class ProjectStatusSummaryResponse(BaseModel):
    """描述某一类 Project 资源的总数与状态分布。"""

    total: int = Field(description="资源总数")
    status_counts: dict[str, int] = Field(default_factory=dict, description="状态计数字典")


class ProjectSummaryResponse(BaseModel):
    """描述工作台可直接消费的项目级聚合摘要响应。"""

    project_id: str = Field(description="所属 Project id")
    generated_at: str = Field(description="聚合快照生成时间")
    datasets: ProjectDatasetInventoryResponse = Field(description="数据集目录聚合摘要")
    imports: ProjectStatusSummaryResponse = Field(description="数据集导入聚合摘要")
    exports: ProjectStatusSummaryResponse = Field(description="数据集导出聚合摘要")
    training: ProjectStatusSummaryResponse = Field(description="训练任务聚合摘要")
    validation: ProjectStatusSummaryResponse = Field(description="人工验证 session 聚合摘要")
    evaluation: ProjectStatusSummaryResponse = Field(description="评估任务聚合摘要")
    conversion: ProjectStatusSummaryResponse = Field(description="转换任务聚合摘要")
    inference: ProjectStatusSummaryResponse = Field(description="推理任务聚合摘要")
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
    - file_id：公开文件稳定 id，可用于 input_file_id 等调用面。
    - object_key：本地 ObjectStore 相对路径。
    - file_name：文件名。
    - media_type：推断出的媒体类型。
    - size_bytes：文件字节大小。
    - last_modified_at：最近修改时间。
    - content_url：内联读取 URL。
    - download_url：下载 URL。
    """

    project_id: str = Field(description="所属 Project id")
    file_id: str = Field(description="公开文件稳定 id")
    object_key: str = Field(description="本地 ObjectStore 相对路径")
    file_name: str = Field(description="文件名")
    media_type: str = Field(description="推断出的媒体类型")
    size_bytes: int = Field(description="文件字节大小")
    last_modified_at: str = Field(description="最近修改时间")
    content_url: str = Field(description="内联读取 URL")
    download_url: str = Field(description="下载 URL")


class ProjectBootstrapRequestBody(BaseModel):
    """描述 Project 初始化请求体。

    字段：
    - project_id：Project id，同时也是磁盘目录名。
    - display_name：可选展示名称。
    - description：可选项目说明。
    - metadata：附加元数据。
    """

    project_id: str = Field(description="Project id，同时也是磁盘目录名")
    display_name: str | None = Field(default=None, description="可选展示名称")
    description: str | None = Field(default=None, description="可选项目说明")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


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


@projects_router.post(
    "/bootstrap",
    response_model=ProjectCatalogItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def bootstrap_project(
    body: ProjectBootstrapRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(_require_project_bootstrap_principal)],
) -> ProjectCatalogItemResponse:
    """初始化一个 Project 目录和最小工作区骨架。"""

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权初始化该 Project",
            details={"project_id": body.project_id},
        )
    _build_project_bootstrap_service(request).bootstrap_project(
        ProjectBootstrapRequest(
            project_id=body.project_id,
            display_name=body.display_name,
            description=body.description,
            metadata=dict(body.metadata),
        ),
        initialized_by=principal.principal_id,
    )
    return _build_project_catalog_item_response(
        request=request,
        project_id=body.project_id,
        include_summary=True,
    )


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
    "/{project_id}/files",
    response_model=list[ProjectObjectMetadataResponse],
)
def list_project_objects(
    project_id: str,
    request: Request,
    response: Response,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:read", "models:read")),
    ],
    object_prefix: Annotated[str | None, Query(description="Project 内对象前缀")] = None,
    storage_prefix: Annotated[str | None, Query(description="兼容字段；等价于 object_prefix")] = None,
    offset: Annotated[int, Query(ge=0, description="结果偏移量")] = 0,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_LIST_LIMIT, description="最大返回数量"),
    ] = DEFAULT_LIST_LIMIT,
) -> list[ProjectObjectMetadataResponse]:
    """列出一个 Project 公开命名空间中的文件，并直接返回 file_id。"""

    object_entries = _list_project_public_object_entries(
        request=request,
        principal=principal,
        project_id=project_id,
        object_prefix=object_prefix,
        storage_prefix=storage_prefix,
    )
    paged_entries = paginate_sequence(object_entries, response=response, offset=offset, limit=limit)
    return [
        _build_project_object_metadata_response(
            project_id=project_id,
            object_key=object_key,
            file_path=file_path,
        )
        for object_key, file_path in paged_entries
    ]


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
    return _build_project_object_metadata_response(
        project_id=project_id,
        object_key=resolved_object_key,
        file_path=file_path,
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


def _build_project_bootstrap_service(request: Request) -> LocalProjectBootstrapService:
    """基于 application.state 构建 Project bootstrap 服务。"""

    return LocalProjectBootstrapService(dataset_storage=_require_dataset_storage(request))


def _build_project_object_metadata_response(
    *,
    project_id: str,
    object_key: str,
    file_path: Path,
) -> ProjectObjectMetadataResponse:
    """把 Project 公开文件转换为带 file_id 的统一元数据响应。"""

    media_type = _guess_media_type(file_path, object_key=object_key)
    encoded_object_key = quote(object_key, safe="")
    content_url = (
        f"/api/v1/projects/{project_id}/files/content?object_key={encoded_object_key}"
    )
    download_url = f"{content_url}&download=true"
    return ProjectObjectMetadataResponse(
        project_id=project_id,
        file_id=build_public_project_file_id(project_id=project_id, object_key=object_key),
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
    project_manifest = _find_project_manifest(request=request, project_id=project_id)
    summary = None
    if include_summary:
        summary = _build_project_summary_response(
            _build_project_summary_service(request).get_project_summary(project_id)
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


def _find_project_manifest(
    *,
    request: Request,
    project_id: str,
) -> ProjectManifest | None:
    """读取 Project 根目录里的最小 manifest。"""

    return _build_project_bootstrap_service(request).get_project_manifest(project_id)


def _require_project_bootstrap_principal(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes())],
) -> AuthenticatedPrincipal:
    """要求当前主体具备 Project 初始化所需的最小写权限。"""

    if _principal_has_any_scope(principal, "datasets:write", "workflows:write"):
        return principal
    raise PermissionDeniedError(
        "当前主体缺少 Project 初始化所需的写权限",
        details={"required_any_scope": ("datasets:write", "workflows:write")},
    )


def _principal_has_any_scope(principal: AuthenticatedPrincipal, *required_scopes: str) -> bool:
    """判断主体是否具备任一要求 scope。"""

    for required_scope in required_scopes:
        for granted_scope in principal.scopes:
            if granted_scope == "*" or granted_scope == required_scope:
                return True
            if granted_scope.endswith(":*") and required_scope.startswith(granted_scope[:-1]):
                return True
    return False


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


def _list_project_public_object_entries(
    *,
    request: Request,
    principal: AuthenticatedPrincipal,
    project_id: str,
    object_prefix: str | None,
    storage_prefix: str | None,
) -> list[tuple[str, Path]]:
    """列出一个 Project 公开命名空间中的文件路径。"""

    _ensure_project_known_and_visible(
        request=request,
        principal=principal,
        project_id=project_id,
    )
    dataset_storage = _require_dataset_storage(request)
    resolved_object_prefix = _resolve_requested_object_prefix(
        object_prefix=object_prefix,
        storage_prefix=storage_prefix,
    )

    if resolved_object_prefix is None:
        scan_root = dataset_storage.resolve(f"projects/{project_id}")
        if not scan_root.exists():
            return []
        candidate_paths = [
            file_path
            for file_path in sorted(scan_root.rglob("*"))
            if file_path.is_file()
        ]
    else:
        if not is_public_project_object_key(project_id=project_id, object_key=resolved_object_prefix):
            raise InvalidRequestError(
                "当前接口只允许列出 Project 公开文件命名空间中的对象文件",
                details={
                    "project_id": project_id,
                    "object_prefix": resolved_object_prefix,
                    "allowed_namespaces": build_public_project_object_namespace_patterns(project_id=project_id),
                },
            )
        scan_root = dataset_storage.resolve(resolved_object_prefix)
        if scan_root.is_file():
            return [(resolved_object_prefix, scan_root)]
        if not scan_root.exists():
            return []
        candidate_paths = [
            file_path
            for file_path in sorted(scan_root.rglob("*"))
            if file_path.is_file()
        ]

    entries: list[tuple[str, Path]] = []
    for file_path in candidate_paths:
        object_key = file_path.relative_to(dataset_storage.root_dir).as_posix()
        if is_public_project_object_key(project_id=project_id, object_key=object_key):
            entries.append((object_key, file_path))
    return entries


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


def _resolve_requested_object_prefix(
    *,
    object_prefix: str | None,
    storage_prefix: str | None,
) -> str | None:
    """统一解析 object_prefix 和兼容 storage_prefix 参数。"""

    candidates = [
        candidate.strip()
        for candidate in (object_prefix, storage_prefix)
        if candidate is not None and candidate.strip()
    ]
    if not candidates:
        return None
    if len(set(candidates)) > 1:
        raise InvalidRequestError(
            "object_prefix 和 storage_prefix 不能同时提供不同的值",
            details={"object_prefix": object_prefix, "storage_prefix": storage_prefix},
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
            app_runtime_observed_state_counts=dict(summary.workflows.app_runtime_observed_state_counts),
        ),
        deployments=ProjectDeploymentSummaryResponse(
            deployment_instance_total=summary.deployments.deployment_instance_total,
            deployment_status_counts=dict(summary.deployments.deployment_status_counts),
        ),
    )