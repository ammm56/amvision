"""Project route 服务装配与可见性规则。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.application.errors import (
    PermissionDeniedError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.project_bootstrap import (
    LocalProjectBootstrapService,
    ProjectManifest,
)
from backend.service.application.project_summary import ProjectSummaryService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.settings import (
    BackendServiceProjectCatalogItemConfig,
    BackendServiceSettings,
)


def build_project_summary_service(request: Request) -> ProjectSummaryService:
    """基于 application.state 构建 ProjectSummaryService。"""

    return ProjectSummaryService(
        session_factory=require_session_factory(request),
        dataset_storage=require_dataset_storage(request),
    )


def build_project_bootstrap_service(request: Request) -> LocalProjectBootstrapService:
    """基于 application.state 构建 Project bootstrap 服务。"""

    return LocalProjectBootstrapService(dataset_storage=require_dataset_storage(request))


def require_backend_service_settings(request: Request) -> BackendServiceSettings:
    """从 application.state 中读取 BackendServiceSettings。"""

    settings = getattr(request.app.state, "backend_service_settings", None)
    if not isinstance(settings, BackendServiceSettings):
        raise ServiceConfigurationError("当前服务尚未完成 backend_service_settings 装配")
    return settings


def require_session_factory(request: Request) -> SessionFactory:
    """从 application.state 中读取 SessionFactory。"""

    session_factory = getattr(request.app.state, "session_factory", None)
    if not isinstance(session_factory, SessionFactory):
        raise ServiceConfigurationError("当前服务尚未完成 session_factory 装配")
    return session_factory


def require_dataset_storage(request: Request) -> LocalDatasetStorage:
    """从 application.state 中读取 LocalDatasetStorage。"""

    dataset_storage = getattr(request.app.state, "dataset_storage", None)
    if not isinstance(dataset_storage, LocalDatasetStorage):
        raise ServiceConfigurationError("当前服务尚未完成 dataset_storage 装配")
    return dataset_storage


def ensure_project_visible(
    *, principal: AuthenticatedPrincipal, project_id: str
) -> None:
    """校验当前主体是否可访问指定 Project。"""

    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": project_id},
        )


def ensure_project_known_and_visible(
    *,
    request: Request,
    principal: AuthenticatedPrincipal,
    project_id: str,
) -> None:
    """校验指定 Project 同时满足可见性和最小可发现性要求。"""

    ensure_project_visible(principal=principal, project_id=project_id)
    if principal.project_ids and project_id in principal.project_ids:
        return
    if project_id in set(list_visible_project_ids(request=request, principal=principal)):
        return
    raise ResourceNotFoundError(
        "请求的 Project 不存在",
        details={"project_id": project_id},
    )


def list_visible_project_ids(
    *,
    request: Request,
    principal: AuthenticatedPrincipal,
) -> tuple[str, ...]:
    """列出当前主体可见的 Project id 列表。"""

    settings = require_backend_service_settings(request)
    if principal.project_ids:
        return tuple(dict.fromkeys(principal.project_ids))

    configured_project_ids = [
        item.project_id.strip()
        for item in settings.projects.items
        if item.project_id.strip()
    ]
    discovered_project_ids = discover_storage_project_ids(require_dataset_storage(request))
    visible_ids = sorted(set(configured_project_ids).union(discovered_project_ids))
    return tuple(visible_ids)


def discover_storage_project_ids(
    dataset_storage: LocalDatasetStorage,
) -> tuple[str, ...]:
    """从本地 ObjectStore 目录发现已存在的 Project id。"""

    projects_dir = dataset_storage.resolve("projects")
    if not projects_dir.exists() or not projects_dir.is_dir():
        return ()
    return tuple(sorted(child.name for child in projects_dir.iterdir() if child.is_dir()))


def find_project_catalog_item(
    *,
    request: Request,
    project_id: str,
) -> BackendServiceProjectCatalogItemConfig | None:
    """在当前配置中查找一个 Project 目录项。"""

    for item in require_backend_service_settings(request).projects.items:
        if item.project_id == project_id:
            return item
    return None


def find_project_manifest(
    *,
    request: Request,
    project_id: str,
) -> ProjectManifest | None:
    """读取 Project 根目录里的最小 manifest。"""

    return build_project_bootstrap_service(request).get_project_manifest(project_id)


def require_project_bootstrap_principal(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes())],
) -> AuthenticatedPrincipal:
    """要求当前主体具备 Project 初始化所需的最小写权限。"""

    if principal_has_any_scope(principal, "datasets:write", "workflows:write"):
        return principal
    raise PermissionDeniedError(
        "当前主体缺少 Project 初始化所需的写权限",
        details={"required_any_scope": ("datasets:write", "workflows:write")},
    )


def principal_has_any_scope(
    principal: AuthenticatedPrincipal, *required_scopes: str
) -> bool:
    """判断主体是否具备任一要求 scope。"""

    for required_scope in required_scopes:
        for granted_scope in principal.scopes:
            if granted_scope == "*" or granted_scope == required_scope:
                return True
            if granted_scope.endswith(":*") and required_scope.startswith(
                granted_scope[:-1]
            ):
                return True
    return False


def resolve_project_storage_path(
    request: Request,
    object_key: str,
) -> Path:
    """把 ObjectStore object key 解析成本地文件路径。"""

    return require_dataset_storage(request).resolve(object_key)

