"""本地用户、登录会话与长期调用 token REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import (
    AuthenticatedPrincipal,
    get_request_bearer_token,
    require_principal,
    require_scopes,
)
from backend.service.application.auth.local_auth_service import (
    LocalAuthBootstrapAdminRequest,
    LocalAuthIssuedUserToken,
    LocalAuthPasswordResetRequest,
    LocalAuthSessionResult,
    LocalAuthService,
    LocalAuthUser,
    LocalAuthUserCreateRequest,
    LocalAuthUserCreateResult,
    LocalAuthUserToken,
    LocalAuthUserTokenCreateRequest,
    LocalAuthUserUpdateRequest,
)
from backend.service.application.auth.provider_registry import AuthProviderDescriptor, AuthProviderRegistry
from backend.service.application.errors import (
    AuthenticationRequiredError,
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.settings import BackendServiceSettings


auth_router = APIRouter(prefix="/auth", tags=["auth"])


class LocalAuthUserContract(BaseModel):
    """描述本地用户的公开返回结构。"""

    user_id: str
    provider_kind: str
    username: str
    display_name: str
    principal_type: str
    project_ids: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    is_active: bool
    created_at: str
    updated_at: str
    last_login_at: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class AuthProviderContract(BaseModel):
    """描述公开可发现的账号 provider 目录项。"""

    provider_id: str
    provider_kind: str
    display_name: str
    enabled: bool
    login_mode: str
    supports_password_login: bool
    supports_refresh: bool
    supports_bootstrap_admin: bool
    supports_user_management: bool
    supports_long_lived_tokens: bool
    issuer_url: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class LocalAuthSessionContract(BaseModel):
    """描述本地登录、bootstrap 与 refresh 的返回结构。"""

    session_id: str
    access_token: str
    token_type: str = "bearer"
    expires_at: str | None = None
    refresh_token: str
    refresh_expires_at: str | None = None
    user: LocalAuthUserContract


class LocalAuthUserTokenContract(BaseModel):
    """描述长期调用 user token 的公开摘要结构。"""

    token_id: str
    user_id: str
    token_name: str
    created_at: str
    expires_at: str | None = None
    last_used_at: str | None = None
    revoked_at: str | None = None
    created_by_user_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class LocalAuthIssuedUserTokenContract(LocalAuthUserTokenContract):
    """描述新签发 user token 的一次性返回结构。"""

    token: str
    token_type: str = "bearer"


class LocalAuthUserCreateContract(BaseModel):
    """描述本地用户创建返回结构。"""

    user: LocalAuthUserContract
    initial_user_token: LocalAuthIssuedUserTokenContract | None = None


class LocalAuthBootstrapAdminRequestBody(BaseModel):
    """描述 bootstrap 管理员请求体。"""

    username: str = Field(description="用户名")
    password: str = Field(description="密码")
    display_name: str | None = Field(default=None, description="可选展示名称")


class LocalAuthLoginRequestBody(BaseModel):
    """描述本地登录请求体。"""

    provider_id: str = Field(default="local", description="账号 provider 标识")
    username: str = Field(description="用户名")
    password: str = Field(description="密码")


class LocalAuthRefreshRequestBody(BaseModel):
    """描述 refresh token 刷新请求体。"""

    refresh_token: str = Field(description="登录返回的 refresh token")


class LocalAuthInitialUserTokenRequestBody(BaseModel):
    """描述创建用户时默认长期调用 token 的请求体。"""

    enabled: bool = Field(default=True, description="是否在创建用户时默认签发长期调用 token")
    token_name: str = Field(default="default", description="token 名称")
    ttl_hours: int | None = Field(default=None, description="相对有效期小时数")
    expires_at: str | None = Field(default=None, description="显式过期时间，ISO8601")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class LocalAuthUserTokenCreateRequestBody(BaseModel):
    """描述长期调用 user token 创建请求体。"""

    token_name: str = Field(default="default", description="token 名称")
    ttl_hours: int | None = Field(default=None, description="相对有效期小时数")
    expires_at: str | None = Field(default=None, description="显式过期时间，ISO8601")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class LocalAuthUserCreateRequestBody(BaseModel):
    """描述本地用户创建请求体。"""

    username: str = Field(description="用户名")
    password: str = Field(description="密码")
    display_name: str | None = Field(default=None, description="展示名称")
    principal_type: str = Field(default="user", description="主体类型")
    project_ids: list[str] = Field(default_factory=list, description="允许访问的 Project id 列表")
    scopes: list[str] = Field(default_factory=list, description="当前用户持有的 scopes")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
    initial_user_token: LocalAuthInitialUserTokenRequestBody | None = Field(
        default_factory=LocalAuthInitialUserTokenRequestBody,
        description="创建用户时的默认长期调用 token 配置；传 null 或 enabled=false 可关闭默认签发",
    )


class LocalAuthUserUpdateRequestBody(BaseModel):
    """描述本地用户更新请求体。"""

    display_name: str | None = Field(default=None, description="展示名称")
    password: str | None = Field(default=None, description="新密码")
    project_ids: list[str] | None = Field(default=None, description="允许访问的 Project id 列表")
    scopes: list[str] | None = Field(default=None, description="当前用户持有的 scopes")
    is_active: bool | None = Field(default=None, description="是否启用")
    metadata: dict[str, object] | None = Field(default=None, description="附加元数据")


class LocalAuthPasswordResetRequestBody(BaseModel):
    """描述本地用户密码重置请求体。"""

    new_password: str = Field(description="新密码")
    revoke_sessions: bool = Field(default=True, description="是否同时撤销全部登录会话与 refresh token")
    revoke_user_tokens: bool = Field(default=False, description="是否同时撤销全部长期调用 token")


@auth_router.post(
    "/bootstrap-admin",
    response_model=LocalAuthSessionContract,
    status_code=status.HTTP_201_CREATED,
)
def bootstrap_local_auth_admin(
    body: LocalAuthBootstrapAdminRequestBody,
    request: Request,
) -> LocalAuthSessionContract:
    """在本地用户表为空时初始化首个管理员账号。"""

    session_result = _build_local_auth_service(request).bootstrap_admin(
        LocalAuthBootstrapAdminRequest(
            username=body.username,
            password=body.password,
            display_name=body.display_name,
        )
    )
    return _build_local_auth_session_contract(session_result)


@auth_router.get(
    "/providers",
    response_model=list[AuthProviderContract],
)
def list_auth_providers(request: Request) -> list[AuthProviderContract]:
    """列出当前公开可发现的账号 provider。"""

    provider_registry = _build_auth_provider_registry(request)
    return [_build_auth_provider_contract(item) for item in provider_registry.list_providers()]


@auth_router.post(
    "/login",
    response_model=LocalAuthSessionContract,
)
def login_local_auth_user(
    body: LocalAuthLoginRequestBody,
    request: Request,
) -> LocalAuthSessionContract:
    """按本地用户名和密码登录，并签发登录会话与 refresh token。"""

    session_result = _build_auth_provider_registry(request).resolve_password_provider(body.provider_id).login(
        username=body.username,
        password=body.password,
    )
    return _build_local_auth_session_contract(session_result)


@auth_router.post(
    "/refresh",
    response_model=LocalAuthSessionContract,
)
def refresh_local_auth_session(
    body: LocalAuthRefreshRequestBody,
    request: Request,
) -> LocalAuthSessionContract:
    """使用 refresh token 刷新登录会话。"""

    session_result = _build_auth_provider_registry(request).resolve_password_provider("local").refresh_session(
        body.refresh_token
    )
    return _build_local_auth_session_contract(session_result)


@auth_router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
def logout_local_auth_user(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
) -> Response:
    """撤销当前请求携带的本地登录会话 access token。"""

    if principal.metadata.get("auth_credential_kind") != "session":
        raise InvalidRequestError("当前 Bearer token 不是登录会话，不能执行 logout")
    access_token = get_request_bearer_token(request)
    if access_token is None:
        raise AuthenticationRequiredError("当前请求未携带 Bearer token")
    revoked = _build_local_auth_service(request).revoke_session_access_token(
        access_token,
        expected_user_id=principal.principal_id,
        actor_user_id=principal.principal_id,
    )
    if not revoked:
        raise InvalidRequestError("当前 access token 不支持本地注销")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.get(
    "/users",
    response_model=list[LocalAuthUserContract],
)
def list_local_auth_users(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:read"))],
) -> list[LocalAuthUserContract]:
    """列出当前全部本地用户。"""

    _ = principal
    return [_build_local_auth_user_contract(item) for item in _build_local_auth_service(request).list_users()]


@auth_router.post(
    "/users",
    response_model=LocalAuthUserCreateContract,
    status_code=status.HTTP_201_CREATED,
)
def create_local_auth_user(
    body: LocalAuthUserCreateRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:write"))],
) -> LocalAuthUserCreateContract:
    """创建一个本地用户，并默认签发长期调用 token。"""

    user_create_result = _build_local_auth_service(request).create_user(
        LocalAuthUserCreateRequest(
            username=body.username,
            password=body.password,
            display_name=body.display_name,
            principal_type=body.principal_type,
            project_ids=tuple(body.project_ids),
            scopes=tuple(body.scopes),
            metadata=dict(body.metadata),
            initial_user_token=_build_initial_user_token_create_request(body.initial_user_token),
        ),
        created_by_user_id=principal.principal_id,
    )
    return _build_local_auth_user_create_contract(user_create_result)


@auth_router.patch(
    "/users/{user_id}",
    response_model=LocalAuthUserContract,
)
def update_local_auth_user(
    user_id: str,
    body: LocalAuthUserUpdateRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:write"))],
) -> LocalAuthUserContract:
    """更新一个本地用户。"""

    _ = principal
    user = _build_local_auth_service(request).update_user(
        user_id,
        LocalAuthUserUpdateRequest(
            display_name=body.display_name,
            password=body.password,
            project_ids=None if body.project_ids is None else tuple(body.project_ids),
            scopes=None if body.scopes is None else tuple(body.scopes),
            is_active=body.is_active,
            metadata=None if body.metadata is None else dict(body.metadata),
        ),
    )
    return _build_local_auth_user_contract(user)


@auth_router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_local_auth_user(
    user_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:write"))],
) -> Response:
    """删除一个本地用户及其关联凭据。"""

    _build_local_auth_service(request).delete_user(user_id, actor_user_id=principal.principal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.post(
    "/users/{user_id}/reset-password",
    response_model=LocalAuthUserContract,
)
def reset_local_auth_user_password(
    user_id: str,
    body: LocalAuthPasswordResetRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:write"))],
) -> LocalAuthUserContract:
    """重置一个本地用户密码，并按需撤销其现有凭据。"""

    _ = principal
    user = _build_local_auth_service(request).reset_user_password(
        user_id,
        LocalAuthPasswordResetRequest(
            new_password=body.new_password,
            revoke_sessions=body.revoke_sessions,
            revoke_user_tokens=body.revoke_user_tokens,
        ),
        actor_user_id=principal.principal_id,
    )
    return _build_local_auth_user_contract(user)


@auth_router.get(
    "/users/{user_id}/tokens",
    response_model=list[LocalAuthUserTokenContract],
)
def list_local_auth_user_tokens(
    user_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:read"))],
) -> list[LocalAuthUserTokenContract]:
    """列出一个本地用户的长期调用 token。"""

    _ = principal
    return [_build_local_auth_user_token_contract(item) for item in _build_local_auth_service(request).list_user_tokens(user_id)]


@auth_router.post(
    "/users/{user_id}/tokens",
    response_model=LocalAuthIssuedUserTokenContract,
    status_code=status.HTTP_201_CREATED,
)
def create_local_auth_user_token(
    user_id: str,
    body: LocalAuthUserTokenCreateRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:write"))],
) -> LocalAuthIssuedUserTokenContract:
    """为一个本地用户创建长期调用 token。"""

    issued_token = _build_local_auth_service(request).create_user_token(
        user_id,
        LocalAuthUserTokenCreateRequest(
            token_name=body.token_name,
            ttl_hours=body.ttl_hours,
            expires_at=body.expires_at,
            metadata=dict(body.metadata),
        ),
        created_by_user_id=principal.principal_id,
    )
    return _build_local_auth_issued_user_token_contract(issued_token)


@auth_router.delete(
    "/users/{user_id}/tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_local_auth_user_token(
    user_id: str,
    token_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:write"))],
) -> Response:
    """撤销一个本地用户的长期调用 token。"""

    _ = principal
    revoked = _build_local_auth_service(request).revoke_user_token(
        user_id,
        token_id,
        actor_user_id=principal.principal_id,
    )
    if not revoked:
        raise ResourceNotFoundError(
            "请求的本地 user token 不存在",
            details={"user_id": user_id, "token_id": token_id},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _build_local_auth_service(request: Request) -> LocalAuthService:
    """基于 application.state 构建本地鉴权服务。"""

    return LocalAuthService(
        settings=_require_backend_service_settings(request),
        session_factory=_require_session_factory(request),
    )


def _build_auth_provider_registry(request: Request) -> AuthProviderRegistry:
    """基于 application.state 构建 auth provider 注册表。"""

    return AuthProviderRegistry(
        settings=_require_backend_service_settings(request),
        session_factory=_require_session_factory(request),
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


def _build_local_auth_session_contract(session_result: LocalAuthSessionResult) -> LocalAuthSessionContract:
    """构造本地登录会话返回结构。"""

    return LocalAuthSessionContract(
        session_id=session_result.session_id,
        access_token=session_result.access_token,
        token_type="bearer",
        expires_at=session_result.access_expires_at,
        refresh_token=session_result.refresh_token,
        refresh_expires_at=session_result.refresh_expires_at,
        user=_build_local_auth_user_contract(session_result.user),
    )


def _build_auth_provider_contract(provider: AuthProviderDescriptor) -> AuthProviderContract:
    """构造 auth provider 目录响应结构。"""

    return AuthProviderContract(
        provider_id=provider.provider_id,
        provider_kind=provider.provider_kind,
        display_name=provider.display_name,
        enabled=provider.enabled,
        login_mode=provider.login_mode,
        supports_password_login=provider.supports_password_login,
        supports_refresh=provider.supports_refresh,
        supports_bootstrap_admin=provider.supports_bootstrap_admin,
        supports_user_management=provider.supports_user_management,
        supports_long_lived_tokens=provider.supports_long_lived_tokens,
        issuer_url=provider.issuer_url,
        metadata=dict(provider.metadata),
    )


def _build_local_auth_user_create_contract(user_create_result: LocalAuthUserCreateResult) -> LocalAuthUserCreateContract:
    """构造本地用户创建返回结构。"""

    return LocalAuthUserCreateContract(
        user=_build_local_auth_user_contract(user_create_result.user),
        initial_user_token=None
        if user_create_result.initial_user_token is None
        else _build_local_auth_issued_user_token_contract(user_create_result.initial_user_token),
    )


def _build_local_auth_user_contract(user: LocalAuthUser) -> LocalAuthUserContract:
    """构造本地用户返回结构。"""

    return LocalAuthUserContract(
        user_id=user.user_id,
        provider_kind=user.provider_kind,
        username=user.username,
        display_name=user.display_name,
        principal_type=user.principal_type,
        project_ids=list(user.project_ids),
        scopes=list(user.scopes),
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
        metadata=dict(user.metadata),
    )


def _build_local_auth_user_token_contract(user_token: LocalAuthUserToken) -> LocalAuthUserTokenContract:
    """构造长期调用 user token 摘要结构。"""

    return LocalAuthUserTokenContract(
        token_id=user_token.token_id,
        user_id=user_token.user_id,
        token_name=user_token.token_name,
        created_at=user_token.created_at,
        expires_at=user_token.expires_at,
        last_used_at=user_token.last_used_at,
        revoked_at=user_token.revoked_at,
        created_by_user_id=user_token.created_by_user_id,
        metadata=dict(user_token.metadata),
    )


def _build_local_auth_issued_user_token_contract(
    issued_user_token: LocalAuthIssuedUserToken,
) -> LocalAuthIssuedUserTokenContract:
    """构造新签发 user token 的一次性返回结构。"""

    summary = _build_local_auth_user_token_contract(issued_user_token.user_token)
    return LocalAuthIssuedUserTokenContract(
        token_id=summary.token_id,
        user_id=summary.user_id,
        token_name=summary.token_name,
        token=issued_user_token.token,
        token_type="bearer",
        created_at=summary.created_at,
        expires_at=summary.expires_at,
        last_used_at=summary.last_used_at,
        revoked_at=summary.revoked_at,
        created_by_user_id=summary.created_by_user_id,
        metadata=dict(summary.metadata),
    )


def _build_initial_user_token_create_request(
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