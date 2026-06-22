"""通用任务路由的项目可见性校验。"""

from __future__ import annotations

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError


def ensure_project_writable(*, principal: AuthenticatedPrincipal, project_id: str) -> None:
    """校验当前主体是否可以在指定 Project 下创建任务。"""

    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": project_id},
        )


def resolve_visible_project_ids(
    *,
    principal: AuthenticatedPrincipal,
    project_id: str | None,
) -> tuple[str, ...]:
    """根据主体权限和查询条件解析可查询的 Project 范围。"""

    if project_id is not None:
        if principal.project_ids and project_id not in principal.project_ids:
            raise ResourceNotFoundError(
                "找不到指定的任务范围",
                details={"project_id": project_id},
            )
        return (project_id,)

    if principal.project_ids:
        return principal.project_ids

    raise InvalidRequestError("查询任务列表时必须提供 project_id")


def ensure_task_visible(
    *,
    principal: AuthenticatedPrincipal,
    task_project_id: str,
    task_id: str,
) -> None:
    """校验当前主体是否可以访问指定任务。"""

    if principal.project_ids and task_project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的任务",
            details={"task_id": task_id},
        )
