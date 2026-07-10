"""非 detection 训练任务响应构建。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.task_training.catalog import (
    read_optional_str,
    read_training_control_payload,
    resolve_model_type,
    resolve_resume_checkpoint_object_key,
    resolve_task_type,
)
from backend.service.api.rest.v1.routes.task_training.schemas import (
    TrainingTaskActionName,
    TrainingTaskControlPhase,
    TrainingTaskControlStatusResponse,
    TrainingTaskDetailResponse,
    TrainingTaskEventResponse,
    TrainingTaskSummaryResponse,
)
from backend.service.domain.tasks.task_records import TaskEvent, TaskRecord


def build_summary_response(task: TaskRecord) -> TrainingTaskSummaryResponse:
    """把 TaskRecord 转成摘要响应。"""

    task_type = resolve_task_type(task)
    task_spec = dict(task.task_spec) if task.task_spec else {}
    result = dict(task.result) if task.result else {}
    metadata = dict(task.metadata) if task.metadata else {}
    progress = dict(task.progress) if task.progress else {}
    training_summary = result.get("summary")
    training_summary_payload = (
        dict(training_summary) if isinstance(training_summary, dict) else {}
    )
    summary_output_files = training_summary_payload.get("output_files")
    summary_output_files_payload = (
        dict(summary_output_files) if isinstance(summary_output_files, dict) else {}
    )
    result_output_files = result.get("output_files")
    result_output_files_payload = (
        dict(result_output_files) if isinstance(result_output_files, dict) else {}
    )
    metrics_summary = training_summary_payload.get("metrics_summary")
    metrics_summary_payload = (
        dict(metrics_summary) if isinstance(metrics_summary, dict) else {}
    )
    return TrainingTaskSummaryResponse(
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
        progress=progress,
        result=result,
        error_message=task.error_message,
        metadata=metadata,
        task_type=task_type,
        model_type=resolve_model_type(
            task, metadata=metadata, result=result, task_spec=task_spec
        ),
        dataset_export_id=read_optional_str(task_spec.get("dataset_export_id"))
        or read_optional_str(result.get("dataset_export_id"))
        or read_optional_str(metadata.get("dataset_export_id")),
        dataset_export_manifest_key=read_optional_str(
            task_spec.get("dataset_export_manifest_key")
        )
        or read_optional_str(task_spec.get("manifest_object_key"))
        or read_optional_str(result.get("dataset_export_manifest_key"))
        or read_optional_str(metadata.get("dataset_export_manifest_key")),
        dataset_version_id=read_optional_str(result.get("dataset_version_id"))
        or read_optional_str(metadata.get("dataset_version_id")),
        format_id=read_optional_str(result.get("format_id"))
        or read_optional_str(metadata.get("format_id")),
        recipe_id=read_optional_str(task_spec.get("recipe_id")),
        model_scale=read_optional_str(task_spec.get("model_scale"))
        or read_optional_str(metadata.get("model_scale")),
        evaluation_interval=_read_optional_int(task_spec.get("evaluation_interval")),
        gpu_count=_read_optional_int(task_spec.get("gpu_count")),
        precision=read_optional_str(task_spec.get("precision")),
        output_model_name=read_optional_str(task_spec.get("output_model_name"))
        or read_optional_str(metadata.get("output_model_name")),
        model_version_id=read_optional_str(result.get("model_version_id"))
        or read_optional_str(training_summary_payload.get("model_version_id")),
        latest_checkpoint_model_version_id=read_optional_str(
            result.get("latest_checkpoint_model_version_id")
        )
        or read_optional_str(
            training_summary_payload.get("latest_checkpoint_model_version_id")
        ),
        output_object_prefix=read_optional_str(result.get("output_object_prefix"))
        or read_optional_str(result.get("output_prefix"))
        or read_optional_str(training_summary_payload.get("output_object_prefix"))
        or read_optional_str(training_summary_payload.get("output_prefix"))
        or read_optional_str(summary_output_files_payload.get("output_object_prefix"))
        or read_optional_str(result_output_files_payload.get("output_object_prefix")),
        checkpoint_object_key=read_optional_str(result.get("checkpoint_object_key"))
        or read_optional_str(training_summary_payload.get("checkpoint_object_key"))
        or read_optional_str(summary_output_files_payload.get("checkpoint_object_key"))
        or read_optional_str(result_output_files_payload.get("checkpoint_object_key")),
        latest_checkpoint_object_key=read_optional_str(
            result.get("latest_checkpoint_object_key")
        )
        or read_optional_str(
            training_summary_payload.get("latest_checkpoint_object_key")
        )
        or read_optional_str(
            summary_output_files_payload.get("latest_checkpoint_object_key")
        )
        or read_optional_str(
            result_output_files_payload.get("latest_checkpoint_object_key")
        ),
        labels_object_key=read_optional_str(result.get("labels_object_key"))
        or read_optional_str(training_summary_payload.get("labels_object_key"))
        or read_optional_str(summary_output_files_payload.get("labels_object_key"))
        or read_optional_str(result_output_files_payload.get("labels_object_key")),
        metrics_object_key=read_optional_str(result.get("metrics_object_key"))
        or read_optional_str(training_summary_payload.get("metrics_object_key"))
        or read_optional_str(summary_output_files_payload.get("metrics_object_key"))
        or read_optional_str(result_output_files_payload.get("metrics_object_key")),
        validation_metrics_object_key=read_optional_str(
            result.get("validation_metrics_object_key")
        )
        or read_optional_str(
            training_summary_payload.get("validation_metrics_object_key")
        )
        or read_optional_str(
            summary_output_files_payload.get("validation_metrics_object_key")
        )
        or read_optional_str(
            result_output_files_payload.get("validation_metrics_object_key")
        ),
        summary_object_key=read_optional_str(result.get("summary_object_key"))
        or read_optional_str(training_summary_payload.get("summary_object_key"))
        or read_optional_str(summary_output_files_payload.get("summary_object_key"))
        or read_optional_str(result_output_files_payload.get("summary_object_key")),
        best_metric_name=read_optional_str(result.get("best_metric_name"))
        or read_optional_str(training_summary_payload.get("best_metric_name"))
        or read_optional_str(metrics_summary_payload.get("best_metric_name"))
        or read_optional_str(progress.get("best_metric_name")),
        best_metric_value=_first_optional_float(
            result.get("best_metric_value"),
            training_summary_payload.get("best_metric_value"),
            metrics_summary_payload.get("best_metric_value"),
            progress.get("best_metric_value"),
        ),
        training_summary=training_summary_payload,
    )


def build_detail_response(
    task: TaskRecord,
    events: tuple[TaskEvent, ...] = (),
) -> TrainingTaskDetailResponse:
    """把 TaskRecord 转成详情响应。"""

    summary = build_summary_response(task)
    return TrainingTaskDetailResponse(
        **summary.model_dump(),
        available_actions=build_training_task_available_actions(task),
        control_status=build_training_task_control_status(task),
        task_spec=dict(task.task_spec) if task.task_spec else {},
        events=[build_training_task_event_response(event) for event in events],
    )


def build_training_task_available_actions(
    task: TaskRecord,
) -> list[TrainingTaskActionName]:
    """根据当前任务状态构建建议展示的控制动作列表。"""

    control = read_training_control_payload(task)
    if task.state == "queued":
        return ["terminate"]
    if task.state == "running":
        if _read_control_flag(control, "terminate_requested"):
            return []
        if _read_control_flag(control, "pause_requested"):
            return ["terminate"]
        if _read_control_flag(control, "save_requested"):
            return ["pause", "terminate"]
        return ["save", "pause", "terminate"]
    if task.state == "paused":
        actions: list[TrainingTaskActionName] = []
        if resolve_resume_checkpoint_object_key(task):
            actions.append("resume")
        actions.extend(["terminate", "delete"])
        return actions
    if task.state in {"succeeded", "failed", "cancelled"}:
        return ["delete"]
    return []


def build_training_task_control_status(
    task: TaskRecord,
) -> TrainingTaskControlStatusResponse:
    """把非 detection 训练控制元数据归一成统一响应。"""

    control = read_training_control_payload(task)
    status: TrainingTaskControlPhase = "idle"
    pending_action: TrainingTaskActionName | None = None
    if _read_control_flag(control, "terminate_requested"):
        status = "terminate_requested"
        pending_action = "terminate"
    elif _read_control_flag(control, "pause_requested"):
        status = "pause_requested"
        pending_action = "pause"
    elif _read_control_flag(control, "save_requested"):
        status = "save_requested"
        pending_action = "save"
    return TrainingTaskControlStatusResponse(
        status=status,
        pending_action=pending_action,
        resume_checkpoint_object_key=resolve_resume_checkpoint_object_key(task),
    )


def build_training_task_event_response(
    event: TaskEvent,
) -> TrainingTaskEventResponse:
    """把 TaskEvent 转成非 detection 训练任务事件响应。"""

    return TrainingTaskEventResponse(
        event_id=event.event_id,
        task_id=event.task_id,
        attempt_id=event.attempt_id,
        event_type=event.event_type,
        created_at=event.created_at,
        message=event.message,
        payload=dict(event.payload) if event.payload else {},
    )


def _read_control_flag(control: dict[str, object], key: str) -> bool:
    """读取布尔控制标记。"""

    return bool(control.get(key) is True)


def _read_optional_int(value: object) -> int | None:
    """读取可选整数。"""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _read_optional_float(value: object) -> float | None:
    """读取可选数值字段。"""

    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _first_optional_float(*values: object) -> float | None:
    """返回第一个存在的可选数值，保留 0.0 这类合法指标。"""

    for value in values:
        parsed = _read_optional_float(value)
        if parsed is not None:
            return parsed
    return None

