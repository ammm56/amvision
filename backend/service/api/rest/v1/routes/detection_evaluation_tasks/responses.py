"""detection evaluation 响应模型与构建函数。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DetectionEvaluationTaskSubmissionResponse(BaseModel):
    """描述 detection 评估任务创建响应。"""

    task_id: str = Field(description="评估任务 id")
    status: str = Field(description="评估任务当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    model_type: str = Field(description="模型分类")
    dataset_export_id: str = Field(description="解析后的 DatasetExport id")
    dataset_export_manifest_key: str = Field(description="解析后的导出 manifest object key")
    dataset_version_id: str = Field(description="导出来源的 DatasetVersion id")
    format_id: str = Field(description="评估使用的数据集导出格式 id")
    model_version_id: str = Field(description="待评估 ModelVersion id")


class DetectionEvaluationTaskSummaryResponse(BaseModel):
    """描述 detection 评估任务摘要响应。"""

    task_id: str = Field(description="评估任务 id")
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
    dataset_export_id: str | None = Field(default=None, description="评估输入使用的 DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="评估输入使用的导出 manifest object key")
    dataset_version_id: str | None = Field(default=None, description="评估输入使用的 DatasetVersion id")
    format_id: str | None = Field(default=None, description="评估输入导出格式 id")
    model_version_id: str = Field(description="待评估 ModelVersion id")
    score_threshold: float | None = Field(default=None, description="评估 score threshold")
    nms_threshold: float | None = Field(default=None, description="评估 NMS threshold")
    save_result_package: bool = Field(description="是否输出结果包")
    output_object_prefix: str | None = Field(default=None, description="评估输出目录前缀")
    report_object_key: str | None = Field(default=None, description="评估报告 object key")
    detections_object_key: str | None = Field(default=None, description="检测结果 object key")
    result_package_object_key: str | None = Field(default=None, description="评估结果包 object key")
    map50: float | None = Field(default=None, description="当前评估 map50")
    map50_95: float | None = Field(default=None, description="当前评估 map50_95")
    report_summary: dict[str, object] = Field(default_factory=dict, description="评估摘要")


class DetectionEvaluationTaskEventResponse(BaseModel):
    """描述 detection 评估任务事件响应。"""

    event_id: str = Field(description="事件 id")
    task_id: str = Field(description="所属任务 id")
    attempt_id: str | None = Field(default=None, description="关联尝试 id")
    event_type: str = Field(description="事件类型")
    created_at: str = Field(description="事件时间")
    message: str = Field(description="事件消息")
    payload: dict[str, object] = Field(default_factory=dict, description="事件负载")


class DetectionEvaluationTaskDetailResponse(DetectionEvaluationTaskSummaryResponse):
    """描述 detection 评估任务详情响应。"""

    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[DetectionEvaluationTaskEventResponse] = Field(default_factory=list, description="任务事件列表")


def build_detection_evaluation_task_summary_response(
    task: object,
    *,
    model_type: str,
) -> DetectionEvaluationTaskSummaryResponse:
    """把 detection 评估 TaskRecord 转成摘要响应。"""

    task_spec = dict(task.task_spec)
    result = dict(task.result)
    metadata = dict(task.metadata)
    report_summary = result.get("report_summary")
    report_summary_payload = dict(report_summary) if isinstance(report_summary, dict) else {}
    map50 = result.get("map50")
    map50_95 = result.get("map50_95")
    model_version_id = _read_optional_str(task_spec, "model_version_id")
    if model_version_id is None:
        model_version_id = _read_optional_str(result, "model_version_id") or ""
    return DetectionEvaluationTaskSummaryResponse(
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
            or _read_optional_str(result, "dataset_export_manifest_key")
            or _read_optional_str(metadata, "dataset_export_manifest_key")
        ),
        dataset_version_id=_read_optional_str(result, "dataset_version_id")
        or _read_optional_str(metadata, "dataset_version_id"),
        format_id=_read_optional_str(result, "format_id")
        or _read_optional_str(metadata, "format_id"),
        model_version_id=model_version_id,
        score_threshold=float(task_spec["score_threshold"]) if isinstance(task_spec.get("score_threshold"), int | float) else None,
        nms_threshold=float(task_spec["nms_threshold"]) if isinstance(task_spec.get("nms_threshold"), int | float) else None,
        save_result_package=bool(task_spec.get("save_result_package") is True),
        output_object_prefix=_read_optional_str(result, "output_object_prefix") or _read_optional_str(metadata, "output_object_prefix"),
        report_object_key=_read_optional_str(result, "report_object_key"),
        detections_object_key=_read_optional_str(result, "detections_object_key"),
        result_package_object_key=_read_optional_str(result, "result_package_object_key"),
        map50=float(map50) if isinstance(map50, int | float) else None,
        map50_95=float(map50_95) if isinstance(map50_95, int | float) else None,
        report_summary=report_summary_payload,
    )


def build_detection_evaluation_task_detail_response(
    task: object,
    events: tuple[object, ...],
    *,
    model_type: str,
) -> DetectionEvaluationTaskDetailResponse:
    """把 detection 评估 TaskRecord 转成详情响应。"""

    summary = build_detection_evaluation_task_summary_response(task, model_type=model_type)
    return DetectionEvaluationTaskDetailResponse(
        **summary.model_dump(),
        task_spec=dict(task.task_spec),
        events=[
            DetectionEvaluationTaskEventResponse(
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


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None
