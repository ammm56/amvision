"""system config 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.engine import make_url

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.rest.v1.routes.system.schemas import SystemConfigResponse
from backend.service.api.rest.v1.routes.system.services import require_backend_service_settings
from backend.service.settings import BackendServiceSettings


system_config_router = APIRouter()

_SENSITIVE_CONFIG_KEYS = {
    "access_key",
    "api_key",
    "client_secret",
    "password",
    "private_key",
    "secret",
    "token",
}


@system_config_router.get("/config", response_model=SystemConfigResponse)
def get_system_config(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("system:read"))],
) -> SystemConfigResponse:
    """返回当前 backend-service 已解析的统一配置快照。

    参数：
    - request：当前 HTTP 请求。
    - principal：具备 system:read scope 的调用主体。

    返回：
    - SystemConfigResponse：已合并 config*.json、环境变量和启动参数后的配置快照。
    """

    del principal
    settings = require_backend_service_settings(request)
    return SystemConfigResponse(
        config=build_system_config_payload(settings),
        metadata={
            "source": "runtime-resolved",
            "secrets_redacted": True,
        },
    )


def build_system_config_payload(settings: BackendServiceSettings) -> dict[str, object]:
    """构造可返回给前端的配置快照。

    参数：
    - settings：当前进程使用的 backend-service 统一配置。

    返回：
    - dict[str, object]：遮蔽敏感值后的配置快照。
    """

    dumped_config = settings.model_dump(mode="json")
    redacted_config = _redact_config_value(dumped_config)
    return redacted_config if isinstance(redacted_config, dict) else {}


def _redact_config_value(value: object) -> object:
    """递归遮蔽配置中的敏感值。"""

    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_config_key(key_text):
                result[key_text] = "***"
            elif key_text == "url" and isinstance(item, str):
                result[key_text] = _sanitize_database_url(item)
            else:
                result[key_text] = _redact_config_value(item)
        return result
    if isinstance(value, list):
        return [_redact_config_value(item) for item in value]
    return value


def _is_sensitive_config_key(key: str) -> bool:
    """判断配置键是否承载敏感值。"""

    normalized_key = key.casefold()
    return normalized_key in _SENSITIVE_CONFIG_KEYS or any(
        normalized_key.endswith(f"_{suffix}") for suffix in _SENSITIVE_CONFIG_KEYS
    )


def _sanitize_database_url(value: str) -> str:
    """隐藏数据库 URL 中的密码字段。"""

    try:
        url = make_url(value)
    except Exception:
        return value
    if url.password is None:
        return value
    return str(url.set(password="***"))
