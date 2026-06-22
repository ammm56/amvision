"""auth 路由响应构造工具。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.auth.schemas import (
    AuthProviderContract,
    LocalAuthIssuedUserTokenContract,
    LocalAuthSessionContract,
    LocalAuthUserContract,
    LocalAuthUserCreateContract,
    LocalAuthUserTokenContract,
)
from backend.service.application.auth.local_auth_service import (
    LocalAuthIssuedUserToken,
    LocalAuthSessionResult,
    LocalAuthUser,
    LocalAuthUserCreateResult,
    LocalAuthUserToken,
)
from backend.service.application.auth.provider_registry import AuthProviderDescriptor


def build_local_auth_session_contract(session_result: LocalAuthSessionResult) -> LocalAuthSessionContract:
    """构造本地登录会话返回结构。"""

    return LocalAuthSessionContract(
        session_id=session_result.session_id,
        access_token=session_result.access_token,
        token_type="bearer",
        expires_at=session_result.access_expires_at,
        refresh_token=session_result.refresh_token,
        refresh_expires_at=session_result.refresh_expires_at,
        user=build_local_auth_user_contract(session_result.user),
    )


def build_auth_provider_contract(provider: AuthProviderDescriptor) -> AuthProviderContract:
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


def build_local_auth_user_create_contract(user_create_result: LocalAuthUserCreateResult) -> LocalAuthUserCreateContract:
    """构造本地用户创建返回结构。"""

    return LocalAuthUserCreateContract(
        user=build_local_auth_user_contract(user_create_result.user),
        initial_user_token=None
        if user_create_result.initial_user_token is None
        else build_local_auth_issued_user_token_contract(user_create_result.initial_user_token),
    )


def build_local_auth_user_contract(user: LocalAuthUser) -> LocalAuthUserContract:
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


def build_local_auth_user_token_contract(user_token: LocalAuthUserToken) -> LocalAuthUserTokenContract:
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


def build_local_auth_issued_user_token_contract(
    issued_user_token: LocalAuthIssuedUserToken,
) -> LocalAuthIssuedUserTokenContract:
    """构造新签发 user token 的一次性返回结构。"""

    summary = build_local_auth_user_token_contract(issued_user_token.user_token)
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

