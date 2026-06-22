"""模型评估任务路由公共服务 helper。"""

from __future__ import annotations

from typing import Protocol

from fastapi import Response, status

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory


class _TaskRecord(Protocol):
    """描述 route 层需要读取的任务记录字段。"""

    task_id: str
    task_kind: str
    project_id: str
    state: str


def require_evaluation_project_access(
    *,
    principal: AuthenticatedPrincipal,
    project_id: str,
) -> None:
    """校验当前主体是否可以访问评估任务所属 Project。"""

    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "无权访问该 Project",
            details={"project_id": project_id},
        )


def list_evaluation_task_records(
    *,
    session_factory: SessionFactory,
    project_id: str,
    task_kind: str,
    state: str | None,
    limit: int,
) -> list[object]:
    """按 task kind 列出评估任务记录。"""

    task_service = SqlAlchemyTaskService(session_factory)
    return task_service.list_tasks(
        TaskQueryFilters(
            project_id=project_id,
            task_kind=task_kind,
            state=state,
            limit=limit,
        )
    )


def get_evaluation_task_record(
    *,
    session_factory: SessionFactory,
    task_id: str,
    expected_task_kind: str,
) -> object:
    """读取并校验指定评估任务记录。"""

    detail = SqlAlchemyTaskService(session_factory).get_task(task_id)
    task = detail.task
    if task.task_kind != expected_task_kind:
        raise ResourceNotFoundError(
            "找不到指定的评估任务",
            details={"task_id": task_id},
        )
    return task


def delete_finished_evaluation_task(
    *,
    session_factory: SessionFactory,
    task_id: str,
    expected_task_kind: str,
) -> Response:
    """删除已完成的评估任务。"""

    task_service = SqlAlchemyTaskService(session_factory)
    detail = task_service.get_task(task_id)
    task = detail.task
    if task.task_kind != expected_task_kind:
        raise ResourceNotFoundError(
            "找不到指定的评估任务",
            details={"task_id": task_id},
        )
    if task.state in {"queued", "running"}:
        raise InvalidRequestError(
            "当前评估任务仍在运行中，不能删除",
            details={"task_id": task_id},
        )
    task_service.delete_task(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
