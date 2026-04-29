"""WebSocket 路由定义。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskEventQueryFilters
from backend.service.infrastructure.db.session import SessionFactory


ws_router = APIRouter(prefix="/ws")


@ws_router.websocket("/events")
async def subscribe_events(socket: WebSocket) -> None:
    """建立最小系统事件订阅会话。"""

    await socket.accept()
    await socket.send_json(
        {
            "event_type": "system.connected",
            "event_version": "v1",
        }
    )
    await socket.close(code=1000)


@ws_router.websocket("/tasks/events")
async def subscribe_task_events(socket: WebSocket) -> None:
    """按任务维度建立最小任务事件订阅会话。"""

    principal = _get_socket_principal(socket)
    if principal is None:
        await socket.close(code=4401, reason="authentication_required")
        return
    if not _scope_granted(principal.scopes, "tasks:read"):
        await socket.close(code=4403, reason="permission_denied")
        return

    task_id = socket.query_params.get("task_id")
    if task_id is None or not task_id.strip():
        await socket.close(code=4400, reason="task_id_required")
        return

    session_factory = _get_socket_session_factory(socket)
    if session_factory is None:
        await socket.close(code=1011, reason="session_factory_not_ready")
        return

    service = SqlAlchemyTaskService(session_factory)
    try:
        task_detail = service.get_task(task_id)
    except Exception:
        await socket.close(code=4404, reason="task_not_found")
        return
    if principal.project_ids and task_detail.task.project_id not in principal.project_ids:
        await socket.close(code=4404, reason="task_not_found")
        return

    event_type = socket.query_params.get("event_type")
    after_created_at = socket.query_params.get("after_created_at")
    limit = _parse_limit(socket.query_params.get("limit"))
    sent_event_ids: set[str] = set()

    await socket.accept()
    await socket.send_json(
        {
            "event_type": "tasks.connected",
            "task_id": task_id,
            "filters": {
                "event_type": event_type,
                "after_created_at": after_created_at,
                "limit": limit,
            },
        }
    )

    try:
        while True:
            events = service.list_task_events(
                TaskEventQueryFilters(
                    task_id=task_id,
                    event_type=event_type,
                    after_created_at=after_created_at,
                    limit=limit,
                )
            )
            for event in events:
                if event.event_id in sent_event_ids:
                    continue
                sent_event_ids.add(event.event_id)
                await socket.send_json(
                    {
                        "event_id": event.event_id,
                        "task_id": event.task_id,
                        "attempt_id": event.attempt_id,
                        "event_type": event.event_type,
                        "created_at": event.created_at,
                        "message": event.message,
                        "payload": dict(event.payload),
                    }
                )
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return


def _get_socket_principal(socket: WebSocket) -> AuthenticatedPrincipal | None:
    """从 WebSocket 请求头解析当前主体。"""

    principal_id = socket.headers.get("x-amvision-principal-id")
    if principal_id is None:
        return None

    return AuthenticatedPrincipal(
        principal_id=principal_id,
        principal_type=socket.headers.get("x-amvision-principal-type", "user"),
        project_ids=_parse_csv_header(socket.headers.get("x-amvision-project-ids")),
        scopes=_parse_csv_header(socket.headers.get("x-amvision-scopes")),
    )


def _get_socket_session_factory(socket: WebSocket) -> SessionFactory | None:
    """从 application.state 读取 SessionFactory。"""

    session_factory = getattr(socket.app.state, "session_factory", None)
    if isinstance(session_factory, SessionFactory):
        return session_factory

    return None


def _parse_csv_header(header_value: str | None) -> tuple[str, ...]:
    """把逗号分隔的 header 解析为元组。"""

    if header_value is None or not header_value.strip():
        return ()

    return tuple(item.strip() for item in header_value.split(",") if item.strip())


def _scope_granted(granted_scopes: tuple[str, ...], required_scope: str) -> bool:
    """判断 scope 是否已被授权。"""

    for granted_scope in granted_scopes:
        if granted_scope == "*" or granted_scope == required_scope:
            return True
        if granted_scope.endswith(":*") and required_scope.startswith(granted_scope[:-1]):
            return True

    return False


def _parse_limit(raw_limit: str | None) -> int:
    """解析订阅端请求中的 limit 参数。"""

    if raw_limit is None:
        return 100
    try:
        limit = int(raw_limit)
    except ValueError:
        return 100

    if limit <= 0:
        return 100

    return min(limit, 500)