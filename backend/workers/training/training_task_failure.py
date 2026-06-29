"""训练 worker 失败状态回写工具。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    SqlAlchemyTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory


def mark_training_task_failed(
    *,
    session_factory: SessionFactory,
    payload: dict[str, Any] | str,
    error_message: str,
) -> None:
    """把 worker 边界失败同步写回平台 TaskRecord。"""

    task_id = read_optional_task_id(payload)
    if task_id is None:
        return
    task_service = SqlAlchemyTaskService(session_factory=session_factory)
    try:
        task_record = task_service.get_task(task_id).task
        if task_record.state in {"succeeded", "failed", "cancelled"}:
            return
        task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message="training failed",
                payload={
                    "state": "failed",
                    "error_message": error_message,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
    except Exception:
        return


def read_optional_task_id(payload: dict[str, Any] | str) -> str | None:
    """从队列 payload 读取可选 task_id。"""

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("task_id")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
