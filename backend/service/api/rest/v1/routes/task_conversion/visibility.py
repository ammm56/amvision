"""task-native conversion 任务可见性和筛选辅助。"""

from __future__ import annotations

from typing import Any

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.task_type_support import normalize_platform_task_type
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory


def require_visible_task_conversion_task(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    task_type: str,
    service_entries: dict[str, Any],
    session_factory: SessionFactory,
    include_events: bool,
):
    """读取并校验当前主体可见的 task-native conversion 任务。"""

    task_detail = SqlAlchemyTaskService(session_factory).get_task(task_id, include_events=include_events)
    if principal.project_ids and task_detail.task.project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的转换任务",
            details={"task_id": task_id},
        )
    if task_detail.task.task_kind not in _build_task_kind_set(service_entries):
        raise ResourceNotFoundError(
            f"找不到指定的 {task_type} conversion 任务",
            details={"task_id": task_id},
        )
    if read_task_type(task_detail.task) != task_type:
        raise ResourceNotFoundError(
            f"找不到指定的 {task_type} conversion 任务",
            details={"task_id": task_id},
        )
    return task_detail


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
    raise InvalidRequestError("查询转换任务列表时必须提供 project_id")


def matches_task_conversion_filters(
    *,
    task: object,
    task_type: str,
    source_model_version_id: str | None,
    target_format: str | None,
) -> bool:
    """判断 conversion 任务是否满足 task_type 和公开筛选条件。"""

    if read_task_type(task) != task_type:
        return False
    task_spec = dict(getattr(task, "task_spec", {}) or {})
    task_result = dict(getattr(task, "result", {}) or {})
    if (
        source_model_version_id is not None
        and task_spec.get("source_model_version_id") != source_model_version_id
        and task_result.get("source_model_version_id") != source_model_version_id
    ):
        return False
    if target_format is not None:
        requested_target_formats = task_spec.get("target_formats")
        produced_formats = task_result.get("produced_formats")
        requested_matches = isinstance(requested_target_formats, list) and target_format in requested_target_formats
        produced_matches = isinstance(produced_formats, list) and target_format in produced_formats
        if not requested_matches and not produced_matches:
            return False
    return True


def read_task_type(task: object) -> str | None:
    """从 TaskRecord 的 metadata、result 或 task_spec 中读取 task_type。"""

    for payload_name in ("metadata", "result", "task_spec"):
        payload = dict(getattr(task, payload_name, {}) or {})
        normalized_task_type = normalize_platform_task_type(payload.get("task_type"))
        if normalized_task_type is not None:
            return normalized_task_type
    return None


def _build_task_kind_set(service_entries: dict[str, Any]) -> frozenset[str]:
    """返回当前路由支持的 task_kind 集合。"""

    return frozenset(entry.task_kind for entry in service_entries.values())
