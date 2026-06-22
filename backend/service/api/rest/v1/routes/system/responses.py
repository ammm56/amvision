"""system 路由响应构造工具。"""

from __future__ import annotations

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.api.rest.v1.routes.system.schemas import (
    SystemAuthProviderContract,
    SystemCurrentPrincipalContract,
)


def build_current_principal_contract(
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


def build_auth_provider_contract(provider: object) -> SystemAuthProviderContract:
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

