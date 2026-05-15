"""鉴权 provider 目录与解析服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.service.application.auth.local_auth_service import (
    LocalAuthBootstrapAdminRequest,
    LocalAuthService,
    LocalAuthSessionResult,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.settings import BackendServiceAuthProviderConfig, BackendServiceSettings


LOCAL_AUTH_PROVIDER_ID = "local"


@dataclass(frozen=True)
class AuthProviderDescriptor:
    """描述一个公开可发现的账号 provider。

    字段：
    - provider_id：provider 的稳定标识。
    - provider_kind：provider 类型，例如 local、oidc。
    - display_name：展示名称。
    - enabled：是否对调用方公开。
    - login_mode：登录模式，例如 password、external-browser。
    - supports_password_login：是否支持用户名密码登录。
    - supports_refresh：是否支持 refresh token。
    - supports_bootstrap_admin：是否支持 bootstrap-admin。
    - supports_user_management：是否支持本地用户管理。
    - supports_long_lived_tokens：是否支持长期调用 token。
    - issuer_url：可选 issuer 地址。
    - metadata：附加目录元数据。
    """

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
    metadata: dict[str, object] = field(default_factory=dict)


class PasswordAuthProvider(Protocol):
    """描述支持用户名密码登录的账号 provider。"""

    def describe(self) -> AuthProviderDescriptor:
        """返回 provider 目录摘要。"""

    def bootstrap_admin(self, request: LocalAuthBootstrapAdminRequest) -> LocalAuthSessionResult:
        """在 provider 支持时初始化首个管理员。"""

    def login(self, *, username: str, password: str) -> LocalAuthSessionResult:
        """执行用户名密码登录。"""

    def refresh_session(self, refresh_token: str) -> LocalAuthSessionResult:
        """刷新登录会话。"""


class LocalPasswordAuthProvider:
    """把 LocalAuthService 适配成 provider 抽象。"""

    def __init__(self, *, settings: BackendServiceSettings, session_factory: SessionFactory) -> None:
        """初始化 local provider 适配器。"""

        self.settings = settings
        self.local_auth_service = LocalAuthService(settings=settings, session_factory=session_factory)

    def describe(self) -> AuthProviderDescriptor:
        """返回 local provider 的公开目录信息。"""

        return AuthProviderDescriptor(
            provider_id=LOCAL_AUTH_PROVIDER_ID,
            provider_kind="local",
            display_name="Local Account",
            enabled=self.settings.auth.local_auth.enabled,
            login_mode="password",
            supports_password_login=True,
            supports_refresh=True,
            supports_bootstrap_admin=True,
            supports_user_management=True,
            supports_long_lived_tokens=True,
            metadata={"provider_id": LOCAL_AUTH_PROVIDER_ID},
        )

    def bootstrap_admin(self, request: LocalAuthBootstrapAdminRequest) -> LocalAuthSessionResult:
        """调用 local auth 的 bootstrap-admin。"""

        return self.local_auth_service.bootstrap_admin(request)

    def login(self, *, username: str, password: str) -> LocalAuthSessionResult:
        """调用 local auth 的用户名密码登录。"""

        return self.local_auth_service.login(username=username, password=password)

    def refresh_session(self, refresh_token: str) -> LocalAuthSessionResult:
        """调用 local auth 的 refresh。"""

        return self.local_auth_service.refresh_session(refresh_token)


class AuthProviderRegistry:
    """统一管理可公开发现的账号 provider 与本地 password provider。"""

    def __init__(self, *, settings: BackendServiceSettings, session_factory: SessionFactory) -> None:
        """初始化 provider 注册表。"""

        self.settings = settings
        self.session_factory = session_factory
        self._local_provider = LocalPasswordAuthProvider(settings=settings, session_factory=session_factory)

    def list_providers(self) -> tuple[AuthProviderDescriptor, ...]:
        """返回当前已启用的 provider 目录。"""

        descriptors: list[AuthProviderDescriptor] = []
        local_descriptor = self._local_provider.describe()
        if local_descriptor.enabled:
            descriptors.append(local_descriptor)

        for provider_config in self.settings.auth.providers:
            if not provider_config.enabled:
                continue
            descriptors.append(_build_external_provider_descriptor(provider_config))
        return tuple(descriptors)

    def resolve_password_provider(self, provider_id: str | None) -> PasswordAuthProvider:
        """按 provider_id 解析支持用户名密码登录的 provider。"""

        normalized_provider_id = (provider_id or LOCAL_AUTH_PROVIDER_ID).strip()
        if not normalized_provider_id:
            normalized_provider_id = LOCAL_AUTH_PROVIDER_ID

        local_descriptor = self._local_provider.describe()
        if normalized_provider_id == LOCAL_AUTH_PROVIDER_ID and local_descriptor.enabled:
            return self._local_provider

        provider_descriptor = self.get_provider(normalized_provider_id)
        if provider_descriptor is None:
            raise InvalidRequestError(
                "auth provider 不存在",
                details={"provider_id": normalized_provider_id},
            )
        raise InvalidRequestError(
            "当前 auth provider 不支持 password login",
            details={
                "provider_id": normalized_provider_id,
                "login_mode": provider_descriptor.login_mode,
                "provider_kind": provider_descriptor.provider_kind,
            },
        )

    def get_provider(self, provider_id: str) -> AuthProviderDescriptor | None:
        """按 provider_id 读取一个 provider 目录项。"""

        for provider in self.list_providers():
            if provider.provider_id == provider_id:
                return provider
        return None


def _build_external_provider_descriptor(
    provider_config: BackendServiceAuthProviderConfig,
) -> AuthProviderDescriptor:
    """把配置中的在线 provider 转换成目录摘要。"""

    return AuthProviderDescriptor(
        provider_id=provider_config.provider_id,
        provider_kind=provider_config.provider_kind,
        display_name=provider_config.display_name,
        enabled=provider_config.enabled,
        login_mode=provider_config.login_mode,
        supports_password_login=False,
        supports_refresh=False,
        supports_bootstrap_admin=False,
        supports_user_management=False,
        supports_long_lived_tokens=False,
        issuer_url=provider_config.issuer_url,
        metadata=dict(provider_config.metadata),
    )