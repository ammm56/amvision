"""validation session 路由公共服务。"""

from __future__ import annotations

from backend.service.application.errors import PermissionDeniedError


def require_validation_project_access(
    *,
    principal_project_ids: tuple[str, ...],
    project_id: str,
) -> None:
    """校验当前主体是否允许访问 validation session 所属 Project。"""

    if principal_project_ids and project_id not in principal_project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": project_id},
        )


def build_tensor_spec_payload(spec: object) -> dict[str, object]:
    """把 runtime tensor spec 转成可传给响应模型的字典。"""

    return {
        "name": getattr(spec, "name"),
        "shape": getattr(spec, "shape"),
        "dtype": getattr(spec, "dtype"),
    }

