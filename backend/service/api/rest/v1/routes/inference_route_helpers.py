"""通用 inference 路由辅助函数。"""

from __future__ import annotations

import json
from typing import Literal
from uuid import uuid4

from fastapi import Request
from pydantic import BaseModel, Field
from starlette.datastructures import FormData

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


class InferenceTaskSummaryResponse(BaseModel):
    """描述通用 inference task 摘要。"""

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
    save_result_image: bool = Field(description="是否输出预览图")
    output_object_prefix: str | None = Field(default=None, description="输出目录前缀")
    result_object_key: str | None = Field(default=None, description="结果文件 object key")
    preview_image_object_key: str | None = Field(default=None, description="预览图 object key")
    item_count: int | None = Field(default=None, description="结果项数量")
    latency_ms: float | None = Field(default=None, description="推理耗时")
    result_summary: dict[str, object] = Field(default_factory=dict, description="结果摘要")


class InferenceTaskDetailResponse(InferenceTaskSummaryResponse):
    """描述通用 inference task 详情。"""

    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[dict[str, object]] = Field(default_factory=list, description="任务事件列表")


class InferenceTaskResultResponse(BaseModel):
    """描述通用 inference task 结果读取响应。"""

    file_status: Literal["pending", "ready"] = Field(description="推理结果文件状态")
    task_state: str = Field(description="当前推理任务状态")
    object_key: str | None = Field(default=None, description="结果文件 object key")
    payload: dict[str, object] = Field(default_factory=dict, description="推理结果 JSON 内容")


async def read_inference_http_payload(
    request: Request,
) -> tuple[dict[str, object], dict[str, object]]:
    """按 content-type 读取 inference 请求体和输入源。"""

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
        payload = _normalize_form_payload(form)
        return payload, {
            "input_file_id": payload.get("input_file_id"),
            "input_uri": payload.get("input_uri"),
            "image_base64": payload.get("image_base64"),
            "upload_bytes": upload_bytes,
            "upload_filename": upload_filename,
            "upload_content_type": upload_content_type,
        }
    if content_type.startswith("application/json") or not content_type:
        try:
            payload = await request.json()
        except Exception as error:
            raise InvalidRequestError("请求体不是合法的 JSON") from error
        if not isinstance(payload, dict):
            raise InvalidRequestError("请求体必须是 JSON 对象")
        normalized_payload = {str(key): value for key, value in payload.items()}
        return normalized_payload, {
            "input_file_id": normalized_payload.get("input_file_id"),
            "input_uri": normalized_payload.get("input_uri"),
            "image_base64": normalized_payload.get("image_base64"),
            "upload_bytes": None,
            "upload_filename": None,
            "upload_content_type": None,
        }
    raise InvalidRequestError(
        "当前仅支持 application/json 或 multipart/form-data 推理请求",
        details={"content_type": content_type},
    )


def resolve_inference_http_request_id(request: Request, *, prefix: str) -> str:
    """解析一个稳定的 inference HTTP 请求 id。"""

    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return f"{prefix}-{request_id.strip()}"
    return f"{prefix}-{uuid4().hex}"


def build_inference_task_summary_response(
    task: object,
) -> InferenceTaskSummaryResponse:
    """把推理任务 TaskRecord 转成通用摘要响应。"""

    task_spec = dict(task.task_spec)
    result = dict(task.result)
    metadata = dict(task.metadata)
    result_summary = result.get("result_summary")
    item_count = result.get("item_count")
    if not isinstance(item_count, int):
        detection_count = result.get("detection_count")
        item_count = detection_count if isinstance(detection_count, int) else None
    latency_ms = result.get("latency_ms")
    return InferenceTaskSummaryResponse(
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
        save_result_image=bool(task_spec.get("save_result_image") is True),
        output_object_prefix=_read_optional_str(result, "output_object_prefix"),
        result_object_key=_read_optional_str(result, "result_object_key"),
        preview_image_object_key=_read_optional_str(result, "preview_image_object_key"),
        item_count=item_count,
        latency_ms=float(latency_ms) if isinstance(latency_ms, int | float) else None,
        result_summary=dict(result_summary) if isinstance(result_summary, dict) else {},
    )


def build_inference_task_detail_response(
    task: object,
    events: tuple[object, ...],
) -> InferenceTaskDetailResponse:
    """把推理任务和事件转换为详情响应。"""

    summary = build_inference_task_summary_response(task)
    return InferenceTaskDetailResponse(
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


def require_visible_inference_task(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    task_kind: str,
    resource_label: str,
    include_events: bool,
):
    """读取并校验当前主体可见的 inference task。"""

    service = SqlAlchemyTaskService(session_factory)
    task_detail = service.get_task(task_id, include_events=include_events)
    if principal.project_ids and task_detail.task.project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            f"找不到指定的{resource_label}",
            details={"task_id": task_id},
        )
    if task_detail.task.task_kind != task_kind:
        raise ResourceNotFoundError(
            f"找不到指定的{resource_label}",
            details={"task_id": task_id},
        )
    return task_detail


def read_inference_task_result(
    *,
    task_state: str,
    result_payload: dict[str, object],
    dataset_storage: LocalDatasetStorage,
) -> InferenceTaskResultResponse:
    """读取 task.result 中指向的结果文件。"""

    object_key = result_payload.get("result_object_key")
    if not isinstance(object_key, str) or not object_key.strip():
        if task_state in {"queued", "running"}:
            return InferenceTaskResultResponse(
                file_status="pending",
                task_state=task_state,
                object_key=None,
                payload={},
            )
        raise InvalidRequestError("当前推理任务缺少结果文件")
    resolved_path = dataset_storage.resolve(object_key)
    if not resolved_path.is_file():
        if task_state in {"queued", "running"}:
            return InferenceTaskResultResponse(
                file_status="pending",
                task_state=task_state,
                object_key=object_key,
                payload={},
            )
        raise InvalidRequestError(
            "当前推理任务的结果文件不存在",
            details={"object_key": object_key},
        )
    payload = dataset_storage.read_json(object_key)
    return InferenceTaskResultResponse(
        file_status="ready",
        task_state=task_state,
        object_key=object_key,
        payload=dict(payload) if isinstance(payload, dict) else {},
    )


def _normalize_form_payload(form: FormData) -> dict[str, object]:
    """把 multipart form 里的字段归一为普通字典。"""

    payload: dict[str, object] = {}
    for key, value in form.multi_items():
        if key == "input_image" or not isinstance(value, str):
            continue
        normalized_value = value.strip()
        if not normalized_value:
            payload[str(key)] = None
            continue
        if key == "extra_options":
            try:
                parsed = json.loads(normalized_value)
            except json.JSONDecodeError as error:
                raise InvalidRequestError(
                    "extra_options 不是合法 JSON",
                    details={"extra_options": normalized_value},
                ) from error
            if not isinstance(parsed, dict):
                raise InvalidRequestError("extra_options 必须是 JSON 对象")
            payload[str(key)] = {str(item_key): item for item_key, item in parsed.items()}
            continue
        payload[str(key)] = normalized_value
    return payload


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串。"""

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


__all__ = [
    "InferenceTaskSummaryResponse",
    "InferenceTaskDetailResponse",
    "InferenceTaskResultResponse",
    "build_inference_task_summary_response",
    "build_inference_task_detail_response",
    "read_inference_http_payload",
    "read_inference_task_result",
    "require_visible_inference_task",
    "resolve_inference_http_request_id",
]
