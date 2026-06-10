"""detection training 路由响应模型与辅助函数。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DetectionTrainingTaskActionName = Literal["save", "pause", "resume", "terminate", "delete"]
DetectionTrainingTaskControlPhase = Literal[
    "idle",
    "save_requested",
    "pause_requested",
    "terminate_requested",
    "resume_pending",
]


class DetectionTrainingTaskControlStatusResponse(BaseModel):
    """描述训练详情中的正式控制状态。"""

    status: DetectionTrainingTaskControlPhase = Field(description="当前控制阶段")
    pending_action: DetectionTrainingTaskActionName | None = Field(default=None, description="当前待处理的控制动作")
    requested_at: str | None = Field(default=None, description="当前待处理动作的登记时间")
    requested_by: str | None = Field(default=None, description="当前待处理动作的登记主体 id")
    last_save_at: str | None = Field(default=None, description="最近一次 latest checkpoint 落盘时间")
    last_save_epoch: int | None = Field(default=None, description="最近一次 latest checkpoint 对应 epoch")
    last_save_reason: str | None = Field(default=None, description="最近一次 latest checkpoint 落盘原因")
    last_save_by: str | None = Field(default=None, description="最近一次 latest checkpoint 请求主体 id")
    last_resume_at: str | None = Field(default=None, description="最近一次 resume 请求时间")
    last_resume_by: str | None = Field(default=None, description="最近一次 resume 请求主体 id")
    resume_count: int = Field(default=0, description="当前任务累计 resume 次数")
    resume_checkpoint_object_key: str | None = Field(default=None, description="最近一次 resume 使用或将使用的 checkpoint object key")


class DetectionTrainingTaskEventResponse(BaseModel):
    """描述 detection 训练任务事件响应。"""

    event_id: str = Field(description="事件 id")
    task_id: str = Field(description="所属任务 id")
    attempt_id: str | None = Field(default=None, description="关联尝试 id")
    event_type: str = Field(description="事件类型")
    created_at: str = Field(description="事件时间")
    message: str = Field(description="事件消息")
    payload: dict[str, object] = Field(default_factory=dict, description="事件负载")


class DetectionTrainingTaskSummaryResponse(BaseModel):
    """描述 detection 训练任务摘要响应。"""

    task_id: str = Field(description="训练任务 id")
    display_name: str = Field(description="展示名称")
    project_id: str = Field(description="所属 Project id")
    created_by: str | None = Field(default=None, description="提交主体 id")
    created_at: str = Field(description="创建时间")
    worker_pool: str | None = Field(default=None, description="worker pool 名称")
    state: str = Field(description="当前状态")
    current_attempt_no: int = Field(description="当前尝试序号")
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="结束时间")
    progress: dict[str, object] = Field(default_factory=dict, description="进度快照")
    result: dict[str, object] = Field(default_factory=dict, description="结果快照")
    error_message: str | None = Field(default=None, description="错误消息")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
    model_type: str = Field(description="模型分类")
    dataset_export_id: str | None = Field(default=None, description="训练输入使用的 DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="训练输入使用的导出 manifest object key")
    dataset_version_id: str | None = Field(default=None, description="训练输入使用的 DatasetVersion id")
    format_id: str | None = Field(default=None, description="训练输入导出格式 id")
    recipe_id: str | None = Field(default=None, description="训练 recipe id")
    model_scale: str | None = Field(default=None, description="训练目标的模型 scale")
    evaluation_interval: int | None = Field(default=None, description="真实验证评估周期")
    gpu_count: int | None = Field(default=None, description="请求参与训练的 GPU 数量")
    precision: str | None = Field(default=None, description="请求使用的训练 precision")
    output_model_name: str | None = Field(default=None, description="训练输出模型名")
    model_version_id: str | None = Field(default=None, description="训练输出登记后的 ModelVersion id")
    latest_checkpoint_model_version_id: str | None = Field(default=None, description="自动或手动登记 latest checkpoint 得到的 ModelVersion id")
    output_object_prefix: str | None = Field(default=None, description="训练输出目录前缀")
    checkpoint_object_key: str | None = Field(default=None, description="checkpoint 文件 object key")
    latest_checkpoint_object_key: str | None = Field(default=None, description="最新 checkpoint 文件 object key")
    labels_object_key: str | None = Field(default=None, description="标签文件 object key")
    metrics_object_key: str | None = Field(default=None, description="训练指标文件 object key")
    validation_metrics_object_key: str | None = Field(default=None, description="验证指标文件 object key")
    summary_object_key: str | None = Field(default=None, description="训练摘要文件 object key")
    best_metric_name: str | None = Field(default=None, description="最佳指标名称")
    best_metric_value: float | None = Field(default=None, description="最佳指标值")
    training_summary: dict[str, object] = Field(default_factory=dict, description="训练摘要")


class DetectionTrainingTaskDetailResponse(DetectionTrainingTaskSummaryResponse):
    """描述 detection 训练任务详情响应。"""

    available_actions: list[DetectionTrainingTaskActionName] = Field(description="当前建议展示的训练控制动作列表")
    control_status: DetectionTrainingTaskControlStatusResponse = Field(description="正式训练控制状态")
    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[DetectionTrainingTaskEventResponse] = Field(default_factory=list, description="任务事件列表")


def build_detection_training_task_summary_response(
    task: object,
    *,
    model_type: str,
) -> DetectionTrainingTaskSummaryResponse:
    """把 detection 训练 TaskRecord 转成摘要响应。"""

    task_spec = dict(task.task_spec)
    result = dict(task.result)
    metadata = dict(task.metadata)
    training_summary = result.get("summary")
    training_summary_payload = dict(training_summary) if isinstance(training_summary, dict) else {}
    best_metric_value = result.get("best_metric_value")
    return DetectionTrainingTaskSummaryResponse(
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
        model_type=model_type,
        dataset_export_id=_read_optional_str(task_spec, "dataset_export_id"),
        dataset_export_manifest_key=(
            _read_optional_str(task_spec, "dataset_export_manifest_key")
            or _read_optional_str(task_spec, "manifest_object_key")
        ),
        dataset_version_id=_read_optional_str(result, "dataset_version_id")
        or _read_optional_str(metadata, "dataset_version_id"),
        format_id=_read_optional_str(result, "format_id")
        or _read_optional_str(metadata, "format_id"),
        recipe_id=_read_optional_str(task_spec, "recipe_id"),
        model_scale=_read_optional_str(task_spec, "model_scale"),
        evaluation_interval=_read_optional_int(task_spec, "evaluation_interval"),
        gpu_count=_read_optional_int(task_spec, "gpu_count"),
        precision=_read_optional_str(task_spec, "precision"),
        output_model_name=_read_optional_str(task_spec, "output_model_name"),
        model_version_id=_read_optional_str(result, "model_version_id")
        or _read_optional_str(training_summary_payload, "model_version_id"),
        latest_checkpoint_model_version_id=_resolve_detection_training_latest_checkpoint_model_version_id(
            task,
            training_summary_payload,
        ),
        output_object_prefix=_read_optional_str(result, "output_object_prefix")
        or _read_optional_str(metadata, "output_object_prefix"),
        checkpoint_object_key=_read_optional_str(result, "checkpoint_object_key"),
        latest_checkpoint_object_key=_read_optional_str(result, "latest_checkpoint_object_key"),
        labels_object_key=_read_optional_str(result, "labels_object_key"),
        metrics_object_key=_read_optional_str(result, "metrics_object_key"),
        validation_metrics_object_key=_read_optional_str(result, "validation_metrics_object_key"),
        summary_object_key=_read_optional_str(result, "summary_object_key"),
        best_metric_name=_read_optional_str(result, "best_metric_name"),
        best_metric_value=float(best_metric_value) if isinstance(best_metric_value, int | float) else None,
        training_summary=training_summary_payload,
    )


def build_detection_training_task_detail_response(
    task: object,
    events: tuple[object, ...],
    *,
    model_type: str,
) -> DetectionTrainingTaskDetailResponse:
    """把 detection 训练任务和事件转换为详情响应。"""

    summary = build_detection_training_task_summary_response(task, model_type=model_type)
    return DetectionTrainingTaskDetailResponse(
        **summary.model_dump(),
        available_actions=build_detection_training_task_available_actions(task),
        control_status=build_detection_training_task_control_status(task),
        task_spec=dict(task.task_spec),
        events=[build_detection_training_task_event_response(event) for event in events],
    )


def build_detection_training_task_available_actions(
    task: object,
) -> list[DetectionTrainingTaskActionName]:
    """根据当前任务状态构建建议展示的控制动作列表。"""

    control = _read_detection_training_control(task)
    if task.state == "queued":
        return ["terminate"]
    if task.state == "running":
        if _read_detection_training_control_flag(control, "terminate_requested"):
            return []
        if _read_detection_training_control_flag(control, "pause_requested"):
            return ["terminate"]
        if _read_detection_training_control_flag(control, "save_requested"):
            return ["pause", "terminate"]
        return ["save", "pause", "terminate"]
    if task.state == "paused":
        actions: list[DetectionTrainingTaskActionName] = []
        if _resolve_detection_training_resume_checkpoint_object_key(task, control):
            actions.append("resume")
        actions.extend(["terminate", "delete"])
        return actions
    if task.state in {"succeeded", "failed", "cancelled"}:
        return ["delete"]
    return []


def build_detection_training_task_control_status(
    task: object,
) -> DetectionTrainingTaskControlStatusResponse:
    """把训练控制元数据归一成 detection 正式控制状态响应。"""

    control = _read_detection_training_control(task)
    status_value: DetectionTrainingTaskControlPhase = "idle"
    pending_action: DetectionTrainingTaskActionName | None = None
    requested_at: str | None = None
    requested_by: str | None = None
    if _read_detection_training_control_flag(control, "terminate_requested"):
        status_value = "terminate_requested"
        pending_action = "terminate"
        requested_at = _read_optional_str(control, "terminate_requested_at")
        requested_by = _read_optional_str(control, "terminate_requested_by")
    elif _read_detection_training_control_flag(control, "pause_requested"):
        status_value = "pause_requested"
        pending_action = "pause"
        requested_at = _read_optional_str(control, "pause_requested_at")
        requested_by = _read_optional_str(control, "pause_requested_by")
    elif _read_detection_training_control_flag(control, "save_requested"):
        status_value = "save_requested"
        pending_action = "save"
        requested_at = _read_optional_str(control, "save_requested_at")
        requested_by = _read_optional_str(control, "save_requested_by")
    elif _read_detection_training_control_flag(control, "resume_pending"):
        status_value = "resume_pending"
        pending_action = "resume"
        requested_at = _read_optional_str(control, "resume_requested_at")
        requested_by = _read_optional_str(control, "resume_requested_by")
    return DetectionTrainingTaskControlStatusResponse(
        status=status_value,
        pending_action=pending_action,
        requested_at=requested_at,
        requested_by=requested_by,
        last_save_at=_read_optional_str(control, "last_save_at"),
        last_save_epoch=_read_optional_int(control, "last_save_epoch"),
        last_save_reason=_read_optional_str(control, "last_save_reason"),
        last_save_by=_read_optional_str(control, "last_save_by"),
        last_resume_at=_read_optional_str(control, "last_resume_at"),
        last_resume_by=_read_optional_str(control, "last_resume_by"),
        resume_count=_read_optional_int(control, "resume_count") or 0,
        resume_checkpoint_object_key=_resolve_detection_training_resume_checkpoint_object_key(task, control),
    )


def build_detection_training_task_event_response(
    event: object,
) -> DetectionTrainingTaskEventResponse:
    """把 TaskEvent 转成 detection 训练任务事件响应。"""

    return DetectionTrainingTaskEventResponse(
        event_id=event.event_id,
        task_id=event.task_id,
        attempt_id=event.attempt_id,
        event_type=event.event_type,
        created_at=event.created_at,
        message=event.message,
        payload=dict(event.payload),
    )


def _read_detection_training_control(task: object) -> dict[str, object]:
    """从训练任务 metadata 中读取控制状态。"""

    metadata = dict(task.metadata)
    raw_control = metadata.get("training_control")
    if isinstance(raw_control, dict):
        return {str(key): value for key, value in raw_control.items()}
    return {}


def _read_detection_training_control_flag(control: dict[str, object], key: str) -> bool:
    """从训练控制字典中读取布尔标记。"""

    return bool(control.get(key) is True)


def _resolve_detection_training_resume_checkpoint_object_key(
    task: object,
    control: dict[str, object],
) -> str | None:
    """解析训练任务当前可用于 resume 的 checkpoint object key。"""

    resume_checkpoint_object_key = _read_optional_str(control, "resume_checkpoint_object_key")
    if resume_checkpoint_object_key is not None:
        return resume_checkpoint_object_key
    result = dict(task.result)
    return _read_optional_str(result, "latest_checkpoint_object_key")


def _read_detection_training_manual_model_version_registration(task: object) -> dict[str, object]:
    """从训练任务 metadata 中读取手动 latest checkpoint 登记信息。"""

    metadata = dict(task.metadata)
    raw_registration = metadata.get("manual_model_version_registration")
    if isinstance(raw_registration, dict):
        return {str(key): value for key, value in raw_registration.items()}
    return {}


def _resolve_detection_training_latest_checkpoint_model_version_id(
    task: object,
    training_summary_payload: dict[str, object],
) -> str | None:
    """解析训练任务 latest checkpoint 对应的 ModelVersion id。"""

    latest_checkpoint_model_version_id = _read_optional_str(
        training_summary_payload,
        "latest_checkpoint_model_version_id",
    )
    if latest_checkpoint_model_version_id is not None:
        return latest_checkpoint_model_version_id
    registration = _read_detection_training_manual_model_version_registration(task)
    return _read_optional_str(registration, "model_version_id")


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _read_optional_int(payload: dict[str, object], key: str) -> int | None:
    """从字典中读取可选整数字段。"""

    value = payload.get(key)
    if isinstance(value, int):
        return value
    return None
