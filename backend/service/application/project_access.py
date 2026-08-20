"""Project 资源访问边界的统一语义。"""

from __future__ import annotations

from backend.service.application.errors import PermissionDeniedError


def require_explicit_project_access(
    *,
    visible_project_ids: tuple[str, ...],
    project_id: str,
) -> None:
    """校验调用方显式指定的 Project。

    ``visible_project_ids`` 为空表示不限制，兼容本地管理员和默认用户。调用方
    显式传入无权访问的 Project 时返回 403；按不透明资源 id 读取时不应调用本
    函数，而应使用 Repository 的可见性查询并返回 404。
    """

    if visible_project_ids and project_id not in visible_project_ids:
        raise PermissionDeniedError(
            "无权访问该 Project",
            details={"project_id": project_id},
        )
