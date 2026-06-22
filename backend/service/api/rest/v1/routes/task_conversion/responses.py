"""task-native conversion API 响应组装。"""

from __future__ import annotations

from backend.service.application.conversions.conversion_result_snapshot import ConversionResultSnapshot
from backend.service.application.errors import ResourceNotFoundError

from .schemas import (
    TaskConversionBuildSummaryResponse,
    TaskConversionResultResponse,
    TaskConversionTaskDetailResponse,
    TaskConversionTaskEventResponse,
    TaskConversionTaskSummaryResponse,
)


def build_task_conversion_task_summary_response(
    task: object,
    *,
    task_type: str,
    model_type: str,
) -> TaskConversionTaskSummaryResponse:
    """把 TaskRecord 转成 task-native conversion 摘要响应。"""

    task_spec = dict(task.task_spec)
    result = dict(task.result)
    metadata = dict(task.metadata)
    report_summary = result.get("report_summary")
    report_summary_payload = dict(report_summary) if isinstance(report_summary, dict) else {}
    raw_builds = result.get("builds")
    builds_payload = (
        [
            TaskConversionBuildSummaryResponse(
                model_build_id=_read_optional_str(item, "model_build_id") or "",
                build_format=_read_optional_str(item, "build_format") or "",
                build_file_id=_read_optional_str(item, "build_file_id") or "",
                build_file_uri=_read_optional_str(item, "build_file_uri") or "",
                metadata=dict(item.get("metadata")) if isinstance(item.get("metadata"), dict) else {},
            )
            for item in raw_builds
            if isinstance(item, dict)
        ]
        if isinstance(raw_builds, list)
        else []
    )
    return TaskConversionTaskSummaryResponse(
        task_id=task.task_id,
        display_name=task.display_name,
        project_id=task.project_id,
        created_by=task.created_by,
        created_at=task.created_at,
        worker_pool=task.worker_pool,
        state=task.state,
        current_attempt_no=task.current_attempt_no,
        started_at=task.started_at,
        finished_at=task.finished_at,
        progress=dict(task.progress),
        result=result,
        error_message=task.error_message,
        metadata=metadata,
        task_type=task_type,
        model_type=model_type,
        source_model_version_id=(
            _read_optional_str(task_spec, "source_model_version_id")
            or _read_optional_str(result, "source_model_version_id")
            or _read_optional_str(metadata, "source_model_version_id")
            or ""
        ),
        target_formats=_read_optional_str_list(task_spec, "target_formats"),
        runtime_profile_id=(
            _read_optional_str(task_spec, "runtime_profile_id")
            or _read_optional_str(metadata, "runtime_profile_id")
        ),
        output_object_prefix=_read_optional_str(result, "output_object_prefix"),
        plan_object_key=_read_optional_str(result, "plan_object_key"),
        report_object_key=_read_optional_str(result, "report_object_key"),
        requested_target_formats=_read_optional_str_list(result, "requested_target_formats"),
        produced_formats=_read_optional_str_list(result, "produced_formats"),
        builds=builds_payload,
        report_summary=report_summary_payload,
    )


def build_task_conversion_task_detail_response(
    task: object,
    events: tuple[object, ...],
    *,
    task_type: str,
    model_type: str,
) -> TaskConversionTaskDetailResponse:
    """把 TaskRecord 转成 task-native conversion 详情响应。"""

    summary = build_task_conversion_task_summary_response(
        task,
        task_type=task_type,
        model_type=model_type,
    )
    return TaskConversionTaskDetailResponse(
        **summary.model_dump(),
        task_spec=dict(task.task_spec),
        events=[
            TaskConversionTaskEventResponse(
                event_id=event.event_id,
                task_id=event.task_id,
                attempt_id=event.attempt_id,
                event_type=event.event_type,
                created_at=event.created_at,
                message=event.message,
                payload=dict(event.payload),
            )
            for event in events
        ],
    )


def build_task_conversion_result_response(
    task_id: str,
    result_snapshot: ConversionResultSnapshot,
) -> TaskConversionResultResponse:
    """把 conversion 结果快照转换为公开响应。"""

    if result_snapshot.file_status not in {"pending", "ready"}:
        raise ResourceNotFoundError(
            "找不到指定的转换结果",
            details={"task_id": task_id},
        )
    return TaskConversionResultResponse(
        file_status=result_snapshot.file_status,
        task_state=result_snapshot.task_state,
        object_key=result_snapshot.object_key,
        payload=dict(result_snapshot.payload),
    )


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _read_optional_str_list(payload: dict[str, object], key: str) -> list[str]:
    """从字典中读取可选字符串列表字段。"""

    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]
