"""detection inference API response schema 与构造函数。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.service.application.errors import ResourceNotFoundError


class DetectionInferenceTaskSubmissionResponse(BaseModel):
    """描述 detection 推理任务创建响应。"""

    task_id: str = Field(description="推理任务 id")
    status: str = Field(description="推理任务当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    deployment_instance_id: str = Field(description="DeploymentInstance id")
    input_uri: str = Field(description="归一化后的输入 URI")
    input_source_kind: str = Field(description="输入来源类型")


class DetectionInferenceRuntimeTensorSpecResponse(BaseModel):
    """描述推理运行时张量规格。"""

    name: str = Field(description="张量名称")
    shape: tuple[int, ...] = Field(description="张量形状")
    dtype: str = Field(description="张量数据类型")


class DetectionInferenceRuntimeSessionInfoResponse(BaseModel):
    """描述推理运行时会话信息。"""

    backend_name: str = Field(description="运行时 backend 名称")
    model_uri: str = Field(description="当前加载模型 URI")
    device_name: str = Field(description="当前执行 device 名称")
    input_spec: DetectionInferenceRuntimeTensorSpecResponse = Field(description="输入张量规格")
    output_spec: DetectionInferenceRuntimeTensorSpecResponse = Field(description="输出张量规格")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加运行时元数据")


class DetectionInferenceDetectionResponse(BaseModel):
    """描述单条推理 detection 结果。"""

    bbox_xyxy: tuple[float, float, float, float] = Field(description="检测框坐标，格式为 xyxy")
    score: float = Field(description="检测得分")
    class_id: int = Field(description="类别 id")
    class_name: str | None = Field(default=None, description="类别名")


class DetectionInferencePayloadResponse(BaseModel):
    """描述同步直返与异步结果共用的推理结果载荷。"""

    request_id: str = Field(description="统一请求 id")
    inference_task_id: str | None = Field(default=None, description="异步推理任务 id；同步场景为空")
    deployment_instance_id: str = Field(description="DeploymentInstance id")
    instance_id: str | None = Field(default=None, description="实际执行推理的实例 id")
    model_version_id: str = Field(description="推理使用的 ModelVersion id")
    model_build_id: str | None = Field(default=None, description="推理使用的 ModelBuild id")
    input_uri: str = Field(description="归一化后的输入 URI")
    input_source_kind: str = Field(description="输入来源类型")
    input_file_id: str | None = Field(default=None, description="Project 公开文件 id；输入不是 file_id 时为空")
    score_threshold: float = Field(description="本次推理阈值")
    save_result_image: bool = Field(description="是否保存预览图")
    return_preview_image_base64: bool = Field(description="是否直接返回预览图 base64")
    image_width: int = Field(description="输入图片宽度")
    image_height: int = Field(description="输入图片高度")
    detection_count: int = Field(description="检测框数量")
    latency_ms: float | None = Field(default=None, description="decode、preprocess、infer、postprocess 四段总耗时，单位毫秒")
    decode_ms: float | None = Field(default=None, description="图片读取或解码耗时，单位毫秒")
    preprocess_ms: float | None = Field(default=None, description="预处理与张量准备耗时，单位毫秒")
    infer_ms: float | None = Field(default=None, description="模型前向推理耗时，单位毫秒")
    postprocess_ms: float | None = Field(default=None, description="后处理与 detection 整理耗时，单位毫秒")
    serialize_ms: float | None = Field(default=None, description="构造响应 JSON 负载耗时，单位毫秒")
    labels: list[str] = Field(default_factory=list, description="类别列表")
    detections: list[DetectionInferenceDetectionResponse] = Field(default_factory=list, description="检测结果列表")
    runtime_session_info: DetectionInferenceRuntimeSessionInfoResponse = Field(description="运行时会话信息")
    preview_image_uri: str | None = Field(default=None, description="预览图 URI 或 object key")
    preview_image_base64: str | None = Field(default=None, description="预览图 base64 内容")
    result_object_key: str | None = Field(default=None, description="结果文件 object key")


class DetectionInferenceTaskSummaryResponse(BaseModel):
    """描述 detection 推理任务摘要响应。"""

    task_id: str = Field(description="推理任务 id")
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
    deployment_instance_id: str = Field(description="DeploymentInstance id")
    instance_id: str | None = Field(default=None, description="实际执行推理的实例 id")
    model_version_id: str | None = Field(default=None, description="解析到的 ModelVersion id")
    model_build_id: str | None = Field(default=None, description="解析到的 ModelBuild id")
    input_uri: str | None = Field(default=None, description="输入 URI")
    input_source_kind: str | None = Field(default=None, description="输入来源类型")
    input_file_id: str | None = Field(default=None, description="平台内输入文件 id")
    score_threshold: float | None = Field(default=None, description="推理阈值")
    save_result_image: bool = Field(description="是否输出预览图")
    output_object_prefix: str | None = Field(default=None, description="输出目录前缀")
    result_object_key: str | None = Field(default=None, description="结果文件 object key")
    preview_image_object_key: str | None = Field(default=None, description="预览图 object key")
    detection_count: int | None = Field(default=None, description="检测框数量")
    latency_ms: float | None = Field(default=None, description="推理耗时")
    result_summary: dict[str, object] = Field(default_factory=dict, description="结果摘要")


class DetectionInferenceTaskDetailResponse(DetectionInferenceTaskSummaryResponse):
    """描述 detection 推理任务详情响应。"""

    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[dict[str, object]] = Field(default_factory=list, description="任务事件列表")


class DetectionInferenceTaskResultResponse(BaseModel):
    """描述 detection 推理结果读取响应。"""

    file_status: Literal["pending", "ready"] = Field(description="推理结果文件状态")
    task_state: str = Field(description="当前推理任务状态")
    object_key: str | None = Field(default=None, description="结果文件 object key")
    payload: dict[str, object] = Field(default_factory=dict, description="推理结果 JSON 内容")


def build_detection_inference_task_summary_response(task: object) -> DetectionInferenceTaskSummaryResponse:
    """把 detection 推理 TaskRecord 转成摘要响应。"""

    task_spec = dict(task.task_spec)
    result = dict(task.result)
    metadata = dict(task.metadata)
    detection_count = result.get("detection_count")
    latency_ms = result.get("latency_ms")
    result_summary = result.get("result_summary")
    return DetectionInferenceTaskSummaryResponse(
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
        deployment_instance_id=require_str(task_spec, "deployment_instance_id"),
        instance_id=read_optional_str(result, "instance_id")
        or read_optional_str(result_summary if isinstance(result_summary, dict) else {}, "instance_id"),
        model_version_id=read_optional_str(result, "model_version_id")
        or read_optional_str(metadata, "model_version_id"),
        model_build_id=read_optional_str(result, "model_build_id")
        or read_optional_str(metadata, "model_build_id"),
        input_uri=read_optional_str(task_spec, "input_uri") or read_optional_str(result, "input_uri"),
        input_source_kind=read_optional_str(task_spec, "input_source_kind")
        or read_optional_str(result, "input_source_kind"),
        input_file_id=read_optional_str(task_spec, "input_file_id"),
        score_threshold=float(task_spec["score_threshold"])
        if isinstance(task_spec.get("score_threshold"), int | float)
        else None,
        save_result_image=bool(task_spec.get("save_result_image") is True),
        output_object_prefix=read_optional_str(result, "output_object_prefix"),
        result_object_key=read_optional_str(result, "result_object_key"),
        preview_image_object_key=read_optional_str(result, "preview_image_object_key"),
        detection_count=detection_count if isinstance(detection_count, int) else None,
        latency_ms=float(latency_ms) if isinstance(latency_ms, int | float) else None,
        result_summary=dict(result_summary) if isinstance(result_summary, dict) else {},
    )


def build_detection_inference_task_detail_response(
    task: object,
    events: tuple[object, ...],
) -> DetectionInferenceTaskDetailResponse:
    """把 detection 推理任务和事件转换为详情响应。"""

    summary = build_detection_inference_task_summary_response(task)
    return DetectionInferenceTaskDetailResponse(
        **summary.model_dump(),
        task_spec=dict(task.task_spec),
        events=[
            {
                "event_id": event.event_id,
                "task_id": event.task_id,
                "attempt_id": event.attempt_id,
                "event_type": event.event_type,
                "created_at": event.created_at,
                "message": event.message,
                "payload": dict(event.payload),
            }
            for event in events
        ],
    )


def read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def require_str(payload: dict[str, object], key: str) -> str:
    """从字典中读取必填字符串。"""

    value = read_optional_str(payload, key)
    if value is None:
        raise ResourceNotFoundError(
            "推理任务缺少必填字段",
            details={"field": key},
        )
    return value
