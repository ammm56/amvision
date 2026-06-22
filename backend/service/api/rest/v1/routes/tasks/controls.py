"""通用任务控制动作。"""

from __future__ import annotations

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.api.rest.v1.routes.tasks.responses import build_task_incremental_event_response
from backend.service.api.rest.v1.routes.tasks.schemas import TaskDetailResponse
from backend.service.api.rest.v1.routes.tasks.visibility import ensure_task_visible
from backend.service.application.errors import InvalidRequestError
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory


def cancel_task_response(
    *,
    task_id: str,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
) -> TaskDetailResponse:
    """取消一条尚未结束的任务并返回本次新增事件。"""

    service = SqlAlchemyTaskService(session_factory)
    task_detail = service.get_task(task_id)
    ensure_task_visible(principal=principal, task_project_id=task_detail.task.project_id, task_id=task_id)
    cancelled_detail = service.cancel_task(task_id, cancelled_by=principal.principal_id)
    if cancelled_detail.task.state != "cancelled":
        raise InvalidRequestError("任务取消失败", details={"task_id": task_id})
    return build_task_incremental_event_response(cancelled_detail.task, cancelled_detail.events)
