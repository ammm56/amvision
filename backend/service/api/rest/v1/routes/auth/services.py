"""auth 路由服务装配工具。"""

from __future__ import annotations

from fastapi import Request

from backend.service.api.rest.v1.routes.auth.schemas import LocalAuthInitialUserTokenRequestBody
from backend.service.application.auth.local_auth_service import (
    LocalAuthService,
    LocalAuthUserTokenCreateRequest,
)
from backend.service.application.auth.provider_registry import AuthProviderRegistry
from backend.service.application.errors import ServiceConfigurationError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.settings import BackendServiceSettings


def build_local_auth_service(request: Request) -> LocalAuthService:
    """基于 application.state 构建本地鉴权服务。"""

    return LocalAuthService(
        settings=require_backend_service_settings(request),
        session_factory=require_session_factory(request),
    )


def build_auth_provider_registry(request: Request) -> AuthProviderRegistry:
    """基于 application.state 构建 auth provider 注册表。"""

    return AuthProviderRegistry(
        settings=require_backend_service_settings(request),
        session_factory=require_session_factory(request),
    )


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


def build_initial_user_token_create_request(
    body: LocalAuthInitialUserTokenRequestBody | None,
) -> LocalAuthUserTokenCreateRequest | None:
    """把创建用户时的默认 token 请求体转换为应用层请求。"""

    if body is None or not body.enabled:
        return None
    return LocalAuthUserTokenCreateRequest(
        token_name=body.token_name,
        ttl_hours=body.ttl_hours,
        expires_at=body.expires_at,
        metadata=dict(body.metadata),
    )

