"""项目工作区读取权限：目录身份与资源类别分别控制。"""

from backend.service.api.deps.auth import (
    AuthenticatedPrincipal,
    require_any_scope_group,
)
from backend.service.application.auth.permissions import scope_granted

require_project_reader = require_any_scope_group(
    ("datasets:read",),
    ("models:read",),
    ("workflows:read",),
    ("tasks:read",),
    ("datasets:write",),
    ("workflows:write",),
)


def project_resource_access(principal: AuthenticatedPrincipal) -> dict[str, bool]:
    """返回能公开给当前账号的资源组，不以按钮隐藏代替响应过滤。"""

    def allowed(scope: str, *pages: str) -> bool:
        """服务账号无页面限制；显式账号同时满足 scope 与页面范围。"""
        return scope_granted(principal.scopes, scope) and (
            principal.allowed_pages is None
            or any(page in principal.allowed_pages for page in pages)
        )

    return {
        "datasets": allowed("datasets:read", "datasets"),
        "models": allowed("models:read", "models"),
        "apps": allowed("workflows:read", "workflow-apps", "workflow-graph"),
        "runtimes": allowed(
            "workflows:read", "workflow-apps", "workflow-monitor", "workflow-app-mode"
        ),
        "deployments": allowed("models:read", "deployments"),
        "tasks": allowed("tasks:read", "tasks", "models"),
    }
