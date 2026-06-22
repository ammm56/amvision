"""通用任务响应构造函数。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.tasks.schemas import (
    TaskDetailResponse,
    TaskEventResponse,
    TaskSummaryResponse,
)


def build_task_summary_response(task: object) -> TaskSummaryResponse:
    """把 TaskRecord 转成摘要响应。"""

    return TaskSummaryResponse(
        task_id=task.task_id,
        task_kind=task.task_kind,
        display_name=task.display_name,
        project_id=task.project_id,
        created_by=task.created_by,
        created_at=task.created_at,
        parent_task_id=task.parent_task_id,
        resource_profile_id=task.resource_profile_id,
        worker_pool=task.worker_pool,
        state=task.state,
        current_attempt_no=task.current_attempt_no,
        started_at=task.started_at,
        finished_at=task.finished_at,
        progress=dict(task.progress),
        result=dict(task.result),
        error_message=task.error_message,
        metadata=dict(task.metadata),
    )


def build_task_detail_response(task: object, events: tuple[object, ...]) -> TaskDetailResponse:
    """把任务和事件转换为详情响应。"""

    return TaskDetailResponse(
        **build_task_summary_response(task).model_dump(),
        task_spec=dict(task.task_spec),
        events=[build_task_event_response(event) for event in events],
    )


def build_task_query_detail_response(task: object, events: tuple[object, ...]) -> TaskDetailResponse:
    """构造普通详情查询响应。

    调用方应按 include_events 语义传入 events；默认轻量模式通常传入空列表。
    """

    return build_task_detail_response(task, events)


def build_task_incremental_event_response(task: object, events: tuple[object, ...]) -> TaskDetailResponse:
    """构造操作后的新增事件响应。

    events 只应包含当前操作新增的事件，不返回历史事件列表。
    """

    return build_task_detail_response(task, events)


def build_task_event_response(event: object) -> TaskEventResponse:
    """把 TaskEvent 转成响应对象。"""

    return TaskEventResponse(
        event_id=event.event_id,
        task_id=event.task_id,
        attempt_id=event.attempt_id,
        event_type=event.event_type,
        created_at=event.created_at,
        message=event.message,
        payload=dict(event.payload),
    )
