"""detection inference 路由响应模型与辅助函数。"""

from __future__ import annotations

import json
from typing import Literal
from uuid import uuid4

from fastapi import Request
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.models.detection_inference_payloads import (
    DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE,
    DetectionInferenceInputSource,
)
from backend.service.application.runtime.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from starlette.datastructures import FormData


_DEFAULT_INFERENCE_SCORE_THRESHOLD = 0.3


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


def _build_detection_inference_task_summary_response(
    task: object,
) -> DetectionInferenceTaskSummaryResponse:
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
        deployment_instance_id=_require_str(task_spec, "deployment_instance_id"),
        instance_id=_read_optional_str(result, "instance_id")
        or _read_optional_str(result_summary if isinstance(result_summary, dict) else {}, "instance_id"),
        model_version_id=_read_optional_str(result, "model_version_id")
        or _read_optional_str(metadata, "model_version_id"),
        model_build_id=_read_optional_str(result, "model_build_id")
        or _read_optional_str(metadata, "model_build_id"),
        input_uri=_read_optional_str(task_spec, "input_uri")
        or _read_optional_str(result, "input_uri"),
        input_source_kind=_read_optional_str(task_spec, "input_source_kind")
        or _read_optional_str(result, "input_source_kind"),
        input_file_id=_read_optional_str(task_spec, "input_file_id"),
        score_threshold=float(task_spec["score_threshold"]) if isinstance(task_spec.get("score_threshold"), int | float) else None,
        save_result_image=bool(task_spec.get("save_result_image") is True),
        output_object_prefix=_read_optional_str(result, "output_object_prefix"),
        result_object_key=_read_optional_str(result, "result_object_key"),
        preview_image_object_key=_read_optional_str(result, "preview_image_object_key"),
        detection_count=detection_count if isinstance(detection_count, int) else None,
        latency_ms=float(latency_ms) if isinstance(latency_ms, int | float) else None,
        result_summary=dict(result_summary) if isinstance(result_summary, dict) else {},
    )


def _build_detection_inference_task_detail_response(
    task: object,
    events: tuple[object, ...],
) -> DetectionInferenceTaskDetailResponse:
    """把 detection 推理任务和事件转换为详情响应。"""

    summary = _build_detection_inference_task_summary_response(task)
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


def _ensure_visible_detection_deployment(
    *,
    principal: AuthenticatedPrincipal,
    deployment_project_id: str,
    deployment_instance_id: str,
) -> None:
    """校验当前主体是否可以访问指定 detection DeploymentInstance。"""

    if principal.project_ids and deployment_project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的 DeploymentInstance",
            details={"deployment_instance_id": deployment_instance_id},
        )


def _matches_detection_inference_filters(
    *,
    task: object,
    deployment_instance_id: str | None,
) -> bool:
    """判断 detection 推理任务是否满足额外筛选条件。"""

    if deployment_instance_id is None:
        return True
    task_spec = dict(task.task_spec)
    return task_spec.get("deployment_instance_id") == deployment_instance_id


def _require_running_detection_deployment_process(
    *,
    deployment_process_supervisor: DeploymentProcessSupervisor,
    process_config: object,
    runtime_mode: str,
) -> None:
    """校验目标 detection deployment 子进程已经处于 running 状态。"""

    status = deployment_process_supervisor.get_status(process_config)
    if status.process_state == "running":
        return
    raise InvalidRequestError(
        "当前 deployment 进程尚未启动，请先调用 start 或 warmup 接口",
        details={
            "deployment_instance_id": getattr(process_config, "deployment_instance_id", None),
            "runtime_mode": runtime_mode,
            "process_state": status.process_state,
            "required_actions": [f"{runtime_mode}/start", f"{runtime_mode}/warmup"],
        },
    )


async def _read_detection_inference_request_payload(
    request: Request,
) -> tuple[dict[str, object], DetectionInferenceInputSource]:
    """按 content-type 读取 detection 推理请求，并保留 one-of 输入源信息。"""

    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("input_image")
        upload_bytes = None
        upload_filename = None
        upload_content_type = None
        if upload is not None:
            if not hasattr(upload, "read"):
                raise InvalidRequestError("input_image 必须是有效的上传文件")
            upload_bytes = await upload.read()
            upload_filename = getattr(upload, "filename", None)
            upload_content_type = getattr(upload, "content_type", None)
        payload = {
            "project_id": _read_optional_form_str(form, "project_id"),
            "deployment_instance_id": _read_optional_form_str(form, "deployment_instance_id"),
            "model_type": _read_optional_form_str(form, "model_type"),
            "input_file_id": _read_optional_form_str(form, "input_file_id"),
            "input_uri": _read_optional_form_str(form, "input_uri"),
            "image_base64": _read_optional_form_str(form, "image_base64"),
            "input_transport_mode": _read_optional_form_str(form, "input_transport_mode") or DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE,
            "score_threshold": _parse_optional_form_float(form.get("score_threshold"), field_name="score_threshold"),
            "save_result_image": _parse_optional_form_bool(form.get("save_result_image"), field_name="save_result_image", default=False),
            "return_preview_image_base64": _parse_optional_form_bool(form.get("return_preview_image_base64"), field_name="return_preview_image_base64", default=False),
            "extra_options": _parse_optional_form_json_dict(form.get("extra_options"), field_name="extra_options"),
            "display_name": _read_optional_form_str(form, "display_name") or "",
        }
        return payload, DetectionInferenceInputSource(
            input_file_id=payload.get("input_file_id") if isinstance(payload.get("input_file_id"), str) else None,
            input_uri=payload.get("input_uri") if isinstance(payload.get("input_uri"), str) else None,
            image_base64=payload.get("image_base64") if isinstance(payload.get("image_base64"), str) else None,
            upload_bytes=upload_bytes,
            upload_filename=upload_filename,
            upload_content_type=upload_content_type,
        )
    if content_type.startswith("application/json") or not content_type:
        try:
            payload = await request.json()
        except Exception as error:
            raise InvalidRequestError("请求体不是合法的 JSON") from error
        if not isinstance(payload, dict):
            raise InvalidRequestError("请求体必须是 JSON 对象")
        normalized_payload = {str(key): value for key, value in payload.items()}
        return normalized_payload, DetectionInferenceInputSource(
            input_file_id=normalized_payload.get("input_file_id") if isinstance(normalized_payload.get("input_file_id"), str) else None,
            input_uri=normalized_payload.get("input_uri") if isinstance(normalized_payload.get("input_uri"), str) else None,
            image_base64=normalized_payload.get("image_base64") if isinstance(normalized_payload.get("image_base64"), str) else None,
        )
    raise InvalidRequestError(
        "当前仅支持 application/json 或 multipart/form-data 推理请求",
        details={"content_type": content_type},
    )


def _resolve_detection_http_request_id(request: Request, *, prefix: str) -> str:
    """解析一个稳定的 detection HTTP 请求 id。"""

    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return f"{prefix}-{request_id.strip()}"
    return f"{prefix}-{uuid4().hex}"


def _read_detection_async_inference_service_id(request: Request) -> str | None:
    """读取当前 detection async inference service 稳定 id。"""

    value = getattr(request.app.state, "detection_async_inference_service_id", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _resolve_detection_requested_score_threshold(value: float | None) -> float:
    """解析 detection 推理阈值；未提供时回落到默认值。"""

    if isinstance(value, int | float):
        threshold = float(value)
    else:
        threshold = _DEFAULT_INFERENCE_SCORE_THRESHOLD
    if threshold < 0 or threshold > 1:
        raise InvalidRequestError(
            "score_threshold 必须位于 0 到 1 之间",
            details={"score_threshold": threshold},
        )
    return threshold


def _read_optional_form_str(form: FormData, key: str) -> str | None:
    """从 multipart form 中读取可选字符串字段。"""

    value = form.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_optional_form_float(value: object, *, field_name: str) -> float | None:
    """把 multipart form 字段解析为可选浮点数。"""

    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as error:
            raise InvalidRequestError(
                f"{field_name} 必须是合法数字",
                details={field_name: value},
            ) from error
    raise InvalidRequestError(
        f"{field_name} 必须是合法数字",
        details={field_name: value},
    )


def _parse_optional_form_bool(value: object, *, field_name: str, default: bool) -> bool:
    """把 multipart form 字段解析为布尔值。"""

    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise InvalidRequestError(
        f"{field_name} 必须是合法布尔值",
        details={field_name: value},
    )


def _parse_optional_form_json_dict(value: object, *, field_name: str) -> dict[str, object]:
    """把 multipart form 中的 JSON 字段解析为字典。"""

    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise InvalidRequestError(
                f"{field_name} 不是合法 JSON",
                details={field_name: value},
            ) from error
        if isinstance(parsed, dict):
            return {str(key): item for key, item in parsed.items()}
    raise InvalidRequestError(
        f"{field_name} 必须是 JSON 对象",
        details={field_name: value},
    )


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _require_str(payload: dict[str, object], key: str) -> str:
    """从字典中读取必填字符串。"""

    value = _read_optional_str(payload, key)
    if value is None:
        raise ResourceNotFoundError(
            "推理任务缺少必填字段",
            details={"field": key},
        )
    return value
