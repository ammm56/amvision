"""通用 scope 与页面目录；不参与执行器或数据面处理。"""

from collections.abc import Sequence

from backend.service.application.errors import InvalidRequestError


# 页面最低读取能力；新建/修改等操作在对应请求入口另行校验。
PAGE_SCOPES: dict[str, tuple[str, ...]] = {
    "projects": ("workflows:read", "models:read"),
    "tasks": ("tasks:read",),
    "datasets": ("datasets:read",),
    "models": ("models:read",),
    "deployments": ("models:read",),
    "inference": ("models:read",),
    "workflow-graph": ("workflows:read",),
    "workflow-apps": ("workflows:read",),
    "workflow-monitor": ("workflows:read",),
    "workflow-app-mode": ("workflows:read",),
    "integrations": ("workflows:read",),
    "custom-nodes": ("workflows:read",),
    "settings-preferences": (),
    "settings-startup": (),
    "settings-session": (),
    "settings-services": ("auth:read",),
    "settings-system": ("auth:read",),
    "settings-accounts": ("auth:read",),
}


def scope_granted(scopes: Sequence[str], required: str) -> bool:
    """按原精确、全局和前缀通配规则检查所需 scope。"""
    return any(
        value == "*"
        or value == required
        or (value.endswith(":*") and required.startswith(value[:-1]))
        for value in scopes
    )


def normalize_allowed_pages(pages: Sequence[str] | None) -> tuple[str, ...] | None:
    """校验页面 ID，保留 null 兼容模式并稳定去重。"""
    if pages is None:
        return None
    if any(not isinstance(page, str) or page not in PAGE_SCOPES for page in pages):
        raise InvalidRequestError("页面权限包含未登记的页面")
    return tuple(dict.fromkeys(pages))


def validate_page_access(pages: Sequence[str] | None, scopes: Sequence[str]) -> None:
    """拒绝显式页面与最低读取能力矛盾的组合。"""
    if pages is not None:
        for page in pages:
            if not all(scope_granted(scopes, scope) for scope in PAGE_SCOPES[page]):
                raise InvalidRequestError(
                    "页面缺少必要查看权限",
                    details={"page_id": page, "required_scopes": PAGE_SCOPES[page]},
                )
    if scope_granted(scopes, "workflows:invoke") and not scope_granted(
        scopes, "workflows:read"
    ):
        raise InvalidRequestError("执行工作流需要查看工作流权限")


def is_account_administrator(
    scopes: Sequence[str], pages: Sequence[str] | None
) -> bool:
    """判断账号是否保有用户管理入口与操作能力。"""
    return (pages is None or "settings-accounts" in pages) and all(
        scope_granted(scopes, scope) for scope in ("auth:read", "auth:write")
    )
