"""系统级 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.service.application.unit_of_work import UnitOfWork
from backend.service.api.deps.auth import (
    AuthenticatedPrincipal,
    get_optional_principal,
    require_principal,
    require_scopes,
)
from backend.service.api.deps.db import get_unit_of_work
from backend.service.api.rest.v1.routes.projects import (
    ProjectCatalogItemResponse,
    _build_project_catalog_item_response,
    _list_visible_project_ids,
)
from backend.service.application.local_buffers import LocalBufferBrokerProcessSupervisor
from backend.service.application.auth.provider_registry import AuthProviderRegistry
from backend.service.application.project_summary import get_supported_project_summary_topics
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.settings import BackendServiceSettings
from backend.contracts.datasets.exports.dataset_formats import IMPLEMENTED_DATASET_EXPORT_FORMATS


system_router = APIRouter(prefix="/system", tags=["system"])


class SystemCurrentPrincipalContract(BaseModel):
    """描述 system/bootstrap 使用的当前主体摘要。"""

    principal_id: str = Field(description="主体 id")
    principal_type: str = Field(description="主体类型")
    project_ids: list[str] = Field(default_factory=list, description="当前主体可见的 Project id 列表")
    scopes: list[str] = Field(default_factory=list, description="当前主体持有的 scopes")
    username: str | None = Field(default=None, description="用户名")
    display_name: str | None = Field(default=None, description="展示名称")
    auth_source: str | None = Field(default=None, description="当前鉴权来源")
    auth_provider_id: str | None = Field(default=None, description="账号 provider id")
    auth_provider_kind: str | None = Field(default=None, description="账号 provider 类型")
    auth_credential_kind: str | None = Field(default=None, description="凭据类型")
    auth_credential_id: str | None = Field(default=None, description="凭据 id")
    auth_session_id: str | None = Field(default=None, description="登录会话 id")
    auth_token_id: str | None = Field(default=None, description="长期 token id")
    auth_token_name: str | None = Field(default=None, description="长期 token 名称")


class SystemAuthProviderContract(BaseModel):
    """描述 system/bootstrap 中公开的账号 provider 目录项。"""

    provider_id: str = Field(description="provider id")
    provider_kind: str = Field(description="provider 类型")
    display_name: str = Field(description="展示名称")
    enabled: bool = Field(description="是否启用")
    login_mode: str = Field(description="登录模式")
    supports_password_login: bool = Field(description="是否支持密码登录")
    supports_refresh: bool = Field(description="是否支持 refresh")
    supports_bootstrap_admin: bool = Field(description="是否支持 bootstrap-admin")
    supports_user_management: bool = Field(description="是否支持用户管理")
    supports_long_lived_tokens: bool = Field(description="是否支持长期调用 token")
    issuer_url: str | None = Field(default=None, description="可选 issuer 地址")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class DatasetExportCapabilityContract(BaseModel):
    """描述前端需要读取的数据集导出格式能力。"""

    implemented_formats: list[str] = Field(default_factory=list, description="当前已实现并可用的格式")
    default_format: str = Field(description="当前默认导出格式")


class SystemBootstrapCapabilitiesContract(BaseModel):
    """描述 system/bootstrap 返回的关键能力摘要。"""

    project_bootstrap_enabled: bool = Field(description="是否支持 Project 初始化接口")
    dataset_export: DatasetExportCapabilityContract = Field(description="数据集导出格式能力")
    project_summary_topics: list[str] = Field(default_factory=list, description="projects.events 支持的 topic 列表")


class SystemBootstrapResponse(BaseModel):
    """描述前端首屏初始化需要的聚合响应。"""

    auth_mode: str | None = Field(default=None, description="当前鉴权模式")
    bearer_auth_enabled: bool = Field(description="是否启用 Bearer token 鉴权")
    websocket_query_token_enabled: bool = Field(description="WebSocket 是否允许 access_token 查询参数")
    current_user: SystemCurrentPrincipalContract | None = Field(default=None, description="当前已登录主体；未登录时为空")
    providers: list[SystemAuthProviderContract] = Field(default_factory=list, description="公开可发现的账号 provider 列表")
    visible_projects: list[ProjectCatalogItemResponse] = Field(default_factory=list, description="当前主体可见的 Project 目录项")
    capabilities: SystemBootstrapCapabilitiesContract = Field(description="前端需要读取的关键能力摘要")


@system_router.get("/health")
def get_service_health(request: Request) -> dict[str, object]:
    """返回最小健康检查结果。

    参数：
    - request：当前 HTTP 请求。

    返回：
    - 当前服务健康状态。
    """

    return {
        "status": "ok",
        "request_id": request.state.request_id,
        "local_buffer_broker": _build_local_buffer_broker_health(request),
    }


def _build_local_buffer_broker_health(request: Request) -> dict[str, object]:
    """读取 LocalBufferBroker 健康摘要。"""

    supervisor = getattr(request.app.state, "local_buffer_broker_supervisor", None)
    if supervisor is None:
        return {"enabled": False, "state": "not_configured", "running": False}
    if not isinstance(supervisor, LocalBufferBrokerProcessSupervisor):
        return {"enabled": False, "state": "misconfigured", "running": False}
    return supervisor.get_health_summary()


@system_router.get("/bootstrap", response_model=SystemBootstrapResponse)
def get_system_bootstrap(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal | None, Depends(get_optional_principal)],
) -> SystemBootstrapResponse:
    """返回前端首屏初始化需要的聚合响应。"""

    settings = _require_backend_service_settings(request)
    providers = [
        _build_auth_provider_contract(item)
        for item in AuthProviderRegistry(
            settings=settings,
            session_factory=_require_session_factory(request),
        ).list_providers()
    ]
    visible_projects: list[ProjectCatalogItemResponse] = []
    if principal is not None:
        visible_projects = [
            _build_project_catalog_item_response(
                request=request,
                project_id=project_id,
                include_summary=False,
            )
            for project_id in _list_visible_project_ids(request=request, principal=principal)
        ]

    return SystemBootstrapResponse(
        auth_mode=settings.auth.mode,
        bearer_auth_enabled=settings.auth.bearer_auth_enabled(),
        websocket_query_token_enabled=settings.auth.websocket_query_token_enabled,
        current_user=None if principal is None else _build_current_principal_contract(principal),
        providers=providers,
        visible_projects=visible_projects,
        capabilities=SystemBootstrapCapabilitiesContract(
            project_bootstrap_enabled=True,
            dataset_export=DatasetExportCapabilityContract(
                implemented_formats=list(IMPLEMENTED_DATASET_EXPORT_FORMATS),
                default_format=IMPLEMENTED_DATASET_EXPORT_FORMATS[0],
            ),
            project_summary_topics=list(get_supported_project_summary_topics()),
        ),
    )


@system_router.get("/me")
def get_current_principal(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
) -> dict[str, object]:
    """返回当前请求主体信息。

    参数：
    - principal：已通过鉴权的调用主体。

    返回：
    - 当前主体的最小可见信息。
    """

    payload = _build_current_principal_contract(principal).model_dump(mode="json")
    payload["auth_mode"] = getattr(request.app.state.backend_service_settings.auth, "mode", None)
    return payload


@system_router.get("/database")
def get_database_health(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("system:read"))],
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> dict[str, object]:
    """返回数据库连通性检查结果。

    参数：
    - request：当前 HTTP 请求。
    - principal：具备 system:read scope 的调用主体。
    - unit_of_work：当前请求级 Unit of Work。

    返回：
    - 数据库连通性检查结果。
    """

    health_value = unit_of_work.scalar(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "reachable",
        "scalar": health_value,
        "principal_id": principal.principal_id,
        "request_id": request.state.request_id,
    }


def _build_current_principal_contract(
    principal: AuthenticatedPrincipal,
) -> SystemCurrentPrincipalContract:
    """把 AuthenticatedPrincipal 转成稳定响应结构。"""

    return SystemCurrentPrincipalContract(
        principal_id=principal.principal_id,
        principal_type=principal.principal_type,
        project_ids=list(principal.project_ids),
        scopes=list(principal.scopes),
        username=_read_metadata_str(principal, "username"),
        display_name=_read_metadata_str(principal, "display_name"),
        auth_source=_read_metadata_str(principal, "auth_source"),
        auth_provider_id=_read_metadata_str(principal, "auth_provider_id"),
        auth_provider_kind=_read_metadata_str(principal, "auth_provider_kind"),
        auth_credential_kind=_read_metadata_str(principal, "auth_credential_kind"),
        auth_credential_id=_read_metadata_str(principal, "auth_credential_id"),
        auth_session_id=_read_metadata_str(principal, "auth_session_id"),
        auth_token_id=_read_metadata_str(principal, "auth_token_id"),
        auth_token_name=_read_metadata_str(principal, "auth_token_name"),
    )


def _build_auth_provider_contract(provider: object) -> SystemAuthProviderContract:
    """把 provider 描述对象转换为稳定响应结构。"""

    return SystemAuthProviderContract(
        provider_id=str(getattr(provider, "provider_id")),
        provider_kind=str(getattr(provider, "provider_kind")),
        display_name=str(getattr(provider, "display_name")),
        enabled=bool(getattr(provider, "enabled")),
        login_mode=str(getattr(provider, "login_mode")),
        supports_password_login=bool(getattr(provider, "supports_password_login")),
        supports_refresh=bool(getattr(provider, "supports_refresh")),
        supports_bootstrap_admin=bool(getattr(provider, "supports_bootstrap_admin")),
        supports_user_management=bool(getattr(provider, "supports_user_management")),
        supports_long_lived_tokens=bool(getattr(provider, "supports_long_lived_tokens")),
        issuer_url=getattr(provider, "issuer_url", None),
        metadata=dict(getattr(provider, "metadata", {}) or {}),
    )


def _read_metadata_str(principal: AuthenticatedPrincipal, key: str) -> str | None:
    """读取主体 metadata 中的可选字符串字段。"""

    value = principal.metadata.get(key)
    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _require_backend_service_settings(request: Request) -> BackendServiceSettings:
    """从 application.state 中读取 BackendServiceSettings。"""

    settings = getattr(request.app.state, "backend_service_settings", None)
    if not isinstance(settings, BackendServiceSettings):
        raise RuntimeError("当前服务尚未完成 backend_service_settings 装配")
    return settings


def _require_session_factory(request: Request) -> SessionFactory:
    """从 application.state 中读取 SessionFactory。"""

    session_factory = getattr(request.app.state, "session_factory", None)
    if not isinstance(session_factory, SessionFactory):
        raise RuntimeError("当前服务尚未完成 session_factory 装配")
    return session_factory