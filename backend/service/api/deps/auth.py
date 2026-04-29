"""鉴权与权限依赖定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request

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

    principal_id = request.headers.get("x-amvision-principal-id")
    if principal_id is None:
        return None

    principal = AuthenticatedPrincipal(
        principal_id=principal_id,
        principal_type=request.headers.get("x-amvision-principal-type", "user"),
        project_ids=_parse_csv_header(request.headers.get("x-amvision-project-ids")),
        scopes=_parse_csv_header(request.headers.get("x-amvision-scopes")),
    )
    request.state.principal = principal

    return principal


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