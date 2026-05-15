"""默认本地账号种子 seeder。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.service.application.auth.local_auth_service import (
    LocalAuthInitializeDefaultUserRequest,
    LocalAuthService,
)

if TYPE_CHECKING:
    from backend.service.api.bootstrap import BackendServiceRuntime


DEFAULT_LOCAL_AUTH_USERNAME = "amvar"
DEFAULT_LOCAL_AUTH_PASSWORD = "123456"
DEFAULT_LOCAL_AUTH_DISPLAY_NAME = "amvar"
DEFAULT_LOCAL_AUTH_PRINCIPAL_TYPE = "user"
DEFAULT_LOCAL_AUTH_SCOPES = ("*",)
DEFAULT_LOCAL_AUTH_USER_METADATA = {"system_default_user": True}
DEFAULT_LOCAL_AUTH_TOKEN_NAME = "default"
DEFAULT_LOCAL_AUTH_TOKEN = "amvision-default-user-token"
DEFAULT_LOCAL_AUTH_TOKEN_METADATA = {"system_default_user_token": True}


class DefaultLocalAuthSeeder:
    """在空库首次启动时初始化默认本地用户和长期调用 token。"""

    def get_step_name(self) -> str:
        """返回当前 seeder 的稳定步骤名。"""

        return "seed-default-local-auth-user"

    def seed(self, runtime: BackendServiceRuntime) -> None:
        """在启动阶段为空库初始化默认本地用户与默认长期调用 token。

        参数：
        - runtime：当前 backend-service 进程使用的运行时资源。
        """

        if not runtime.settings.auth.local_session_auth_enabled():
            return

        if not runtime.settings.auth.local_auth.initialize_default_user_on_empty_db:
            return

        LocalAuthService(
            settings=runtime.settings,
            session_factory=runtime.session_factory,
        ).initialize_default_user_if_empty(
            LocalAuthInitializeDefaultUserRequest(
                username=DEFAULT_LOCAL_AUTH_USERNAME,
                password=DEFAULT_LOCAL_AUTH_PASSWORD,
                display_name=DEFAULT_LOCAL_AUTH_DISPLAY_NAME,
                principal_type=DEFAULT_LOCAL_AUTH_PRINCIPAL_TYPE,
                scopes=DEFAULT_LOCAL_AUTH_SCOPES,
                metadata=dict(DEFAULT_LOCAL_AUTH_USER_METADATA),
                user_token_name=DEFAULT_LOCAL_AUTH_TOKEN_NAME,
                user_token=DEFAULT_LOCAL_AUTH_TOKEN,
                user_token_metadata=dict(DEFAULT_LOCAL_AUTH_TOKEN_METADATA),
            )
        )