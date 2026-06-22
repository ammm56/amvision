"""detection conversion 路由响应模型与构造函数。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.service.application.conversions.conversion_result_snapshot import (
    ConversionResultSnapshot,
)
from backend.service.api.rest.v1.routes.detection_conversion_tasks.services import (
    resolve_detection_conversion_model_type_from_task,
)
from backend.service.application.errors import ResourceNotFoundError


class DetectionConversionBuildSummaryResponse(BaseModel):
    """描述单个转换输出登记后的 ModelBuild 摘要响应。"""

    model_build_id: str = Field(description="登记后的 ModelBuild id")
    build_format: str = Field(description="build 格式")
    build_file_id: str = Field(description="对应 ModelFile id")
    build_file_uri: str = Field(description="构建产物 object key 或本地 URI")
    metadata: dict[str, object] = Field(default_factory=dict, description="构建元数据")


class DetectionConversionTaskSummaryResponse(BaseModel):
    """描述 detection conversion 任务摘要响应。"""

    task_id: str = Field(description="转换任务 id")
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
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    target_formats: list[str] = Field(default_factory=list, description="请求固化的目标格式列表")
    runtime_profile_id: str | None = Field(default=None, description="目标 RuntimeProfile id")
    output_object_prefix: str | None = Field(default=None, description="输出目录前缀")
    plan_object_key: str | None = Field(default=None, description="转换计划 object key")
    report_object_key: str | None = Field(default=None, description="转换结果报告 object key")
    requested_target_formats: list[str] = Field(default_factory=list, description="提交请求中的目标格式")
    produced_formats: list[str] = Field(default_factory=list, description="实际产出的格式列表")
    builds: list[DetectionConversionBuildSummaryResponse] = Field(default_factory=list, description="登记成功的构建摘要列表")
    report_summary: dict[str, object] = Field(default_factory=dict, description="转换摘要")


class DetectionConversionTaskEventResponse(BaseModel):
    """描述 detection conversion 任务事件响应。"""

    event_id: str = Field(description="事件 id")
    task_id: str = Field(description="所属任务 id")
    attempt_id: str | None = Field(default=None, description="关联尝试 id")
    event_type: str = Field(description="事件类型")
    created_at: str = Field(description="事件时间")
    message: str = Field(description="事件消息")
    payload: dict[str, object] = Field(default_factory=dict, description="事件负载")


class DetectionConversionTaskDetailResponse(DetectionConversionTaskSummaryResponse):
    """描述 detection conversion 任务详情响应。"""

    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[DetectionConversionTaskEventResponse] = Field(default_factory=list, description="任务事件列表")


class DetectionConversionResultResponse(BaseModel):
    """描述 detection conversion 结果读取响应。"""

    file_status: str = Field(description="转换结果文件状态")
    task_state: str = Field(description="当前转换任务状态")
    object_key: str | None = Field(default=None, description="转换结果文件 object key")
    payload: dict[str, object] = Field(default_factory=dict, description="转换结果 JSON 内容")


def build_detection_conversion_task_summary(task: object) -> DetectionConversionTaskSummaryResponse:
    """把 detection conversion TaskRecord 转成摘要响应。"""

    model_type = resolve_detection_conversion_model_type_from_task(task)
    task_spec = dict(task.task_spec)
    result = dict(task.result)
    metadata = dict(task.metadata)
    report_summary = result.get("report_summary")
    report_summary_payload = dict(report_summary) if isinstance(report_summary, dict) else {}
    raw_builds = result.get("builds")
    builds_payload = [
        DetectionConversionBuildSummaryResponse(
            model_build_id=_read_optional_str(item, "model_build_id") or "",
            build_format=_read_optional_str(item, "build_format") or "",
            build_file_id=_read_optional_str(item, "build_file_id") or "",
            build_file_uri=_read_optional_str(item, "build_file_uri") or "",
            metadata=dict(item.get("metadata")) if isinstance(item.get("metadata"), dict) else {},
        )
        for item in raw_builds
        if isinstance(item, dict)
    ] if isinstance(raw_builds, list) else []
    return DetectionConversionTaskSummaryResponse(
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


def build_detection_conversion_task_detail(
    task: object,
    events: tuple[object, ...],
) -> DetectionConversionTaskDetailResponse:
    """把 detection conversion TaskRecord 转成详情响应。"""

    summary = build_detection_conversion_task_summary(task)
    return DetectionConversionTaskDetailResponse(
        **summary.model_dump(),
        task_spec=dict(task.task_spec),
        events=[
            DetectionConversionTaskEventResponse(
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


def build_detection_conversion_result_response(
    task_id: str,
    result_snapshot: ConversionResultSnapshot,
) -> DetectionConversionResultResponse:
    """把 conversion 结果快照转换为公开响应。"""

    if result_snapshot.file_status not in {"pending", "ready"}:
        raise ResourceNotFoundError(
            "找不到指定的转换结果",
            details={"task_id": task_id},
        )
    return DetectionConversionResultResponse(
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
    """从字典中读取可选字符串列表。"""

    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]
