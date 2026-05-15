"""鉴权与权限依赖定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request, WebSocket

from backend.service.settings import BackendServiceSettings
from backend.service.application.errors import AuthenticationRequiredError, PermissionDeniedError


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """描述通过鉴权后的调用主体。

    字段：
    - principal_id：主体 id。
    - principal_type：主体类型，例如 user、service-account、integration-endpoint。
    - project_ids：可访问的 Project id 列表。
    - scopes：当前主体持有的 scope 列表。
    - metadata：附加元数据。
    """

    principal_id: str
    principal_type: str
    project_ids: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


def get_optional_principal(request: Request) -> AuthenticatedPrincipal | None:
    """从请求头中解析当前请求的可选主体。

    参数：
    - request：当前 HTTP 请求。

    返回：
    - 当前请求对应的调用主体；当请求头中没有主体信息时返回 None。
    """

    principal = resolve_request_principal(request)
    if principal is None:
        return None
    request.state.principal = principal
    return principal


def resolve_request_principal(request: Request) -> AuthenticatedPrincipal | None:
    """解析一个 HTTP 请求对应的调用主体。

    参数：
    - request：当前 HTTP 请求。

    返回：
    - AuthenticatedPrincipal | None：解析得到的主体；没有任何认证材料时返回 None。

    异常：
    - AuthenticationRequiredError：当显式提供的 Bearer token 非法时抛出。
    """

    settings = _require_backend_service_settings(request.app)
    if settings.auth.bearer_auth_enabled():
        authorization_header = request.headers.get("authorization")
        if authorization_header is not None and authorization_header.strip():
            bearer_token = _parse_authorization_bearer_token(authorization_header)
            return _resolve_principal_from_static_token(
                settings=settings,
                bearer_token=bearer_token,
                auth_source="bearer-token",
            )

    if settings.auth.development_headers_enabled():
        return _resolve_development_header_principal(
            principal_id=request.headers.get("x-amvision-principal-id"),
            principal_type=request.headers.get("x-amvision-principal-type", "user"),
            project_ids_header=request.headers.get("x-amvision-project-ids"),
            scopes_header=request.headers.get("x-amvision-scopes"),
        )
    return None


def resolve_socket_principal(socket: WebSocket) -> AuthenticatedPrincipal | None:
    """解析一个 WebSocket 连接对应的调用主体。

    参数：
    - socket：当前 WebSocket 连接。

    返回：
    - AuthenticatedPrincipal | None：解析得到的主体；没有任何认证材料时返回 None。

    异常：
    - AuthenticationRequiredError：当 Bearer token 或 access_token 非法时抛出。
    """

    settings = _require_backend_service_settings(socket.app)
    if settings.auth.bearer_auth_enabled() and settings.auth.websocket_query_token_enabled:
        access_token = socket.query_params.get("access_token")
        if access_token is not None and access_token.strip():
            return _resolve_principal_from_static_token(
                settings=settings,
                bearer_token=access_token.strip(),
                auth_source="websocket-query-token",
            )

    if settings.auth.bearer_auth_enabled():
        authorization_header = socket.headers.get("authorization")
        if authorization_header is not None and authorization_header.strip():
            bearer_token = _parse_authorization_bearer_token(authorization_header)
            return _resolve_principal_from_static_token(
                settings=settings,
                bearer_token=bearer_token,
                auth_source="bearer-token",
            )

    if settings.auth.development_headers_enabled():
        return _resolve_development_header_principal(
            principal_id=socket.headers.get("x-amvision-principal-id"),
            principal_type=socket.headers.get("x-amvision-principal-type", "user"),
            project_ids_header=socket.headers.get("x-amvision-project-ids"),
            scopes_header=socket.headers.get("x-amvision-scopes"),
        )
    return None


def require_principal(
    principal: Annotated[AuthenticatedPrincipal | None, Depends(get_optional_principal)],
) -> AuthenticatedPrincipal:
    """要求当前请求必须具备已鉴权主体。

    参数：
    - principal：当前请求解析得到的可选主体。

    返回：
    - 已鉴权主体。

    异常：
    - 当主体不存在时抛出 401。
    """

    if principal is None:
        raise AuthenticationRequiredError()

    return principal


def require_scopes(*required_scopes: str):
    """创建要求主体具备指定 scope 的依赖函数。

    参数：
    - required_scopes：当前接口要求的 scope 列表。

    返回：
    - 可直接挂到 Depends 上的依赖函数。
    """

    def dependency(
        principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
    ) -> AuthenticatedPrincipal:
        """校验当前主体是否具备所需 scope。

        参数：
        - principal：当前请求对应的已鉴权主体。

        返回：
        - 通过校验的主体对象。

        异常：
        - 当缺少任一要求 scope 时抛出 403。
        """

        missing_scopes = tuple(
            scope for scope in required_scopes if not _scope_granted(principal.scopes, scope)
        )
        if missing_scopes:
            raise PermissionDeniedError(
                "当前主体缺少访问所需的 scope",
                details={"required_scopes": missing_scopes},
            )

        return principal

    return dependency


def _parse_csv_header(header_value: str | None) -> tuple[str, ...]:
    """把逗号分隔的请求头值解析为元组。

    参数：
    - header_value：原始请求头值。

    返回：
    - 去除空白后的字符串元组。
    """

    if header_value is None or not header_value.strip():
        return ()

    return tuple(item.strip() for item in header_value.split(",") if item.strip())


def _require_backend_service_settings(application: object) -> BackendServiceSettings:
    """从 application.state 读取 BackendServiceSettings。

    参数：
    - application：FastAPI 或 Starlette 应用对象。

    返回：
    - BackendServiceSettings：当前应用绑定的统一配置。
    """

    state = getattr(application, "state", None)
    settings = getattr(state, "backend_service_settings", None)
    if isinstance(settings, BackendServiceSettings):
        return settings
    return BackendServiceSettings()


def _parse_authorization_bearer_token(authorization_header: str) -> str:
    """解析 Authorization 请求头中的 Bearer token。

    参数：
    - authorization_header：原始 Authorization 请求头值。

    返回：
    - str：提取出的 Bearer token。

    异常：
    - AuthenticationRequiredError：当头部格式不是 Bearer token 时抛出。
    """

    scheme, _, token = authorization_header.partition(" ")
    if scheme.casefold() != "bearer" or not token.strip():
        raise AuthenticationRequiredError("Authorization 请求头必须使用 Bearer token")
    return token.strip()


def _resolve_principal_from_static_token(
    *,
    settings: BackendServiceSettings,
    bearer_token: str,
    auth_source: str,
) -> AuthenticatedPrincipal:
    """按静态 token 配置解析调用主体。

    参数：
    - settings：当前 backend-service 配置。
    - bearer_token：待匹配的 token。
    - auth_source：当前鉴权来源标识。

    返回：
    - AuthenticatedPrincipal：解析得到的主体。

    异常：
    - AuthenticationRequiredError：当 token 未命中任何静态配置时抛出。
    """

    for token_config in settings.auth.static_tokens:
        if token_config.token != bearer_token:
            continue
        metadata = dict(token_config.metadata)
        metadata["auth_source"] = auth_source
        return AuthenticatedPrincipal(
            principal_id=token_config.principal_id,
            principal_type=token_config.principal_type,
            project_ids=tuple(token_config.project_ids),
            scopes=tuple(token_config.scopes),
            metadata=metadata,
        )
    raise AuthenticationRequiredError("当前 Bearer token 无效")


def _resolve_development_header_principal(
    *,
    principal_id: str | None,
    principal_type: str,
    project_ids_header: str | None,
    scopes_header: str | None,
) -> AuthenticatedPrincipal | None:
    """按开发头约定解析调用主体。

    参数：
    - principal_id：主体 id 请求头值。
    - principal_type：主体类型请求头值。
    - project_ids_header：Project 列表请求头值。
    - scopes_header：scope 列表请求头值。

    返回：
    - AuthenticatedPrincipal | None：解析得到的主体；未携带主体 id 时返回 None。
    """

    if principal_id is None:
        return None
    return AuthenticatedPrincipal(
        principal_id=principal_id,
        principal_type=principal_type,
        project_ids=_parse_csv_header(project_ids_header),
        scopes=_parse_csv_header(scopes_header),
        metadata={"auth_source": "development-headers"},
    )


def _scope_granted(granted_scopes: tuple[str, ...], required_scope: str) -> bool:
    """判断某个 scope 是否已被授权。

    参数：
    - granted_scopes：当前主体已拥有的 scope 列表。
    - required_scope：当前接口要求的 scope。

    返回：
    - 当 scope 已被授权时返回 True，否则返回 False。
    """

    for granted_scope in granted_scopes:
        if granted_scope == "*" or granted_scope == required_scope:
            return True
        if granted_scope.endswith(":*") and required_scope.startswith(granted_scope[:-1]):
            return True

    return False