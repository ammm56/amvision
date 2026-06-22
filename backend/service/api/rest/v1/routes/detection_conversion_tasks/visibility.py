"""detection conversion 任务可见性和筛选 helper。"""

from __future__ import annotations

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.api.rest.v1.routes.detection_conversion_tasks.services import (
    DETECTION_CONVERSION_MODEL_TYPE_BY_TASK_KIND,
)
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory


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


def require_visible_detection_conversion_task(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    include_events: bool,
):
    """读取并校验当前主体可见的 detection conversion 任务。"""

    service = SqlAlchemyTaskService(session_factory)
    task_detail = service.get_task(task_id, include_events=include_events)
    if principal.project_ids and task_detail.task.project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的转换任务",
            details={"task_id": task_id},
        )
    if task_detail.task.task_kind not in DETECTION_CONVERSION_MODEL_TYPE_BY_TASK_KIND:
        raise ResourceNotFoundError(
            "找不到指定的 detection conversion 任务",
            details={"task_id": task_id},
        )
    if not matches_detection_conversion_task_type(task_detail.task):
        raise ResourceNotFoundError(
            "找不到指定的 detection conversion 任务",
            details={"task_id": task_id},
        )
    return task_detail


def matches_detection_conversion_task_type(task: object) -> bool:
    """判断转换任务是否属于 detection task_type。"""

    for payload_name in ("metadata", "result", "task_spec"):
        payload = dict(getattr(task, payload_name, {}) or {})
        value = payload.get("task_type")
        if isinstance(value, str) and value.strip():
            return value.strip().lower() == "detection"
    return False


def matches_detection_conversion_filters(
    *,
    task: object,
    source_model_version_id: str | None,
    target_format: str | None,
) -> bool:
    """判断 detection conversion 任务是否满足额外筛选条件。"""

    task_spec = dict(getattr(task, "task_spec", {}))
    task_result = dict(getattr(task, "result", {}))
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
