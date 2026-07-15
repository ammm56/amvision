"""通用任务响应构造函数。"""

from __future__ import annotations

from collections.abc import Mapping

from backend.service.api.rest.v1.routes.tasks.schemas import (
    TaskDetailResponse,
    TaskDetailTargetResponse,
    TaskEventResponse,
    TaskSummaryResponse,
)


_MODEL_TASK_TYPES = ("classification", "segmentation", "pose", "obb", "detection")


def build_task_summary_response(task: object) -> TaskSummaryResponse:
    """把 TaskRecord 转成摘要响应。"""

    detail_target = _resolve_task_detail_target(task)
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
        detail_target=detail_target,
        status_path=_build_task_status_path(task.task_id),
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


def _resolve_task_detail_target(task: object) -> TaskDetailTargetResponse | None:
    """根据任务快照解析业务详情入口。

    通用任务层只做路由归属判断，不承担业务删除和资源生命周期控制。
    无法稳定判断业务资源时返回 None，由前端展示通用任务状态入口。
    """

    task_kind = _normalize_text(getattr(task, "task_kind", ""))
    task_id = str(getattr(task, "task_id", ""))
    task_spec = _as_mapping(getattr(task, "task_spec", {}))
    metadata = _as_mapping(getattr(task, "metadata", {}))
    result = _as_mapping(getattr(task, "result", {}))

    if task_kind == "dataset-import":
        dataset_import_id = _first_text(
            task_spec,
            metadata,
            result,
            keys=("dataset_import_id", "source_import_id"),
        )
        if dataset_import_id:
            return TaskDetailTargetResponse(
                resource_kind="dataset-import",
                resource_id=dataset_import_id,
                path=f"/datasets/imports/{dataset_import_id}",
                label=dataset_import_id,
            )

    if task_kind == "dataset-export":
        dataset_export_id = _first_text(
            task_spec,
            metadata,
            result,
            keys=("dataset_export_id", "source_export_id"),
        )
        if dataset_export_id:
            return TaskDetailTargetResponse(
                resource_kind="dataset-export",
                resource_id=dataset_export_id,
                path=f"/datasets/exports/{dataset_export_id}",
                label=dataset_export_id,
            )

    if "training" in task_kind:
        task_type = _resolve_model_task_type(
            task_kind=task_kind,
            task_spec=task_spec,
            metadata=metadata,
            result=result,
        )
        return TaskDetailTargetResponse(
            resource_kind="model-training-task",
            resource_id=task_id,
            path=f"/models/{task_type}/training-tasks/{task_id}",
            label=task_id,
        )

    if "conversion" in task_kind:
        task_type = _resolve_model_task_type(
            task_kind=task_kind,
            task_spec=task_spec,
            metadata=metadata,
            result=result,
        )
        return TaskDetailTargetResponse(
            resource_kind="model-conversion-task",
            resource_id=task_id,
            path=f"/models/{task_type}/conversion-tasks/{task_id}",
            label=task_id,
        )

    return None


def _build_task_status_path(task_id: str) -> str:
    """构造通用任务状态页路径。"""

    return f"/tasks/{task_id}"


def _resolve_model_task_type(
    *,
    task_kind: str,
    task_spec: Mapping[str, object],
    metadata: Mapping[str, object],
    result: Mapping[str, object],
) -> str:
    """从任务规格、元数据和任务类型中推断模型任务类型。"""

    candidates = [
        _first_text(
            task_spec,
            metadata,
            result,
            keys=("task_type", "model_task_type", "source_task_type"),
        ),
        task_kind,
    ]
    normalized_candidates = [_normalize_text(candidate) for candidate in candidates if candidate]
    for task_type in _MODEL_TASK_TYPES:
        if any(task_type in candidate for candidate in normalized_candidates):
            return task_type
    return "detection"


def _first_text(*sources: Mapping[str, object], keys: tuple[str, ...]) -> str | None:
    """按 key 顺序读取第一个非空字符串值。"""

    for key in keys:
        for source in sources:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _as_mapping(value: object) -> Mapping[str, object]:
    """把可能的 JSON 对象值转换为只读映射视图。"""

    if isinstance(value, Mapping):
        return value
    return {}


def _normalize_text(value: object) -> str:
    """把任意值规范化为小写文本。"""

    return str(value or "").strip().lower()
