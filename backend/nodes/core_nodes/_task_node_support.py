"""任务查询类 core nodes 共享 helper。"""

from __future__ import annotations

from backend.service.application.tasks.task_service import TaskDetail


TASK_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})


def build_task_detail_body(task_detail: TaskDetail) -> dict[str, object]:
    """把 TaskDetail 规范化为 response-body.v1 body。

    参数：
    - task_detail：待序列化的任务详情。

    返回：
    - dict[str, object]：稳定的任务详情 body。
    """

    return {
        "task_id": task_detail.task.task_id,
        "task_kind": task_detail.task.task_kind,
        "display_name": task_detail.task.display_name,
        "project_id": task_detail.task.project_id,
        "created_by": task_detail.task.created_by,
        "created_at": task_detail.task.created_at,
        "parent_task_id": task_detail.task.parent_task_id,
        "resource_profile_id": task_detail.task.resource_profile_id,
        "worker_pool": task_detail.task.worker_pool,
        "state": task_detail.task.state,
        "current_attempt_no": task_detail.task.current_attempt_no,
        "started_at": task_detail.task.started_at,
        "finished_at": task_detail.task.finished_at,
        "progress": dict(task_detail.task.progress),
        "result": dict(task_detail.task.result),
        "error_message": task_detail.task.error_message,
        "metadata": dict(task_detail.task.metadata),
        "task_spec": dict(task_detail.task.task_spec),
        "events": [
            {
                "event_id": event.event_id,
                "task_id": event.task_id,
                "attempt_id": event.attempt_id,
                "event_type": event.event_type,
                "created_at": event.created_at,
                "message": event.message,
                "payload": dict(event.payload),
            }
            for event in task_detail.events
        ],
    }