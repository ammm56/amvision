"""鉴权与权限依赖定义。"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import HTTPException, status


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


def get_optional_principal() -> AuthenticatedPrincipal | None:
    """返回当前请求的可选主体。

    返回：
    - 当前最小骨架默认返回 None，表示后续应由真实鉴权链注入主体。
    """

    return None


def require_principal() -> AuthenticatedPrincipal:
    """要求当前请求必须具备已鉴权主体。

    返回：
    - 已鉴权主体。

    异常：
    - 当主体不存在时抛出 401。
    """

    principal = get_optional_principal()
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="当前请求未通过鉴权",
        )

    return principal