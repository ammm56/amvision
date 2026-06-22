"""通用 task inference 响应模型和转换工具。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
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


def read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串。"""

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


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """兼容内部摘要构建的字符串读取。"""

    return read_optional_str(payload, key)


def _require_str(payload: dict[str, object], key: str) -> str:
    """兼容内部摘要构建的必填字符串读取。"""

    return require_str(payload, key)
