"""detection 训练输出文件读取 helper。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from backend.service.application.errors import ResourceNotFoundError, ServiceConfigurationError
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


DetectionTrainingOutputFileName = Literal[
    "train-metrics",
    "validation-metrics",
    "summary",
    "labels",
    "best-checkpoint",
    "latest-checkpoint",
]
DetectionTrainingOutputFileKind = Literal["json", "text", "checkpoint"]

_DETECTION_TRAINING_OUTPUT_FILE_SPECS: dict[DetectionTrainingOutputFileName, dict[str, str]] = {
    "train-metrics": {
        "object_key_field": "metrics_object_key",
        "relative_path": "artifacts/reports/train-metrics.json",
        "file_kind": "json",
    },
    "validation-metrics": {
        "object_key_field": "validation_metrics_object_key",
        "relative_path": "artifacts/reports/validation-metrics.json",
        "file_kind": "json",
    },
    "summary": {
        "object_key_field": "summary_object_key",
        "relative_path": "artifacts/training-summary.json",
        "file_kind": "json",
    },
    "labels": {
        "object_key_field": "labels_object_key",
        "relative_path": "artifacts/labels.txt",
        "file_kind": "text",
    },
    "best-checkpoint": {
        "object_key_field": "checkpoint_object_key",
        "relative_path": "artifacts/checkpoints/best_ckpt.pth",
        "file_kind": "checkpoint",
    },
    "latest-checkpoint": {
        "object_key_field": "latest_checkpoint_object_key",
        "relative_path": "artifacts/checkpoints/latest_ckpt.pth",
        "file_kind": "checkpoint",
    },
}

_DETECTION_TRAINING_OUTPUT_FILE_ORDER: tuple[DetectionTrainingOutputFileName, ...] = (
    "train-metrics",
    "validation-metrics",
    "summary",
    "labels",
    "best-checkpoint",
    "latest-checkpoint",
)


class DetectionTrainingMetricsFileResponse(BaseModel):
    """描述训练 JSON 输出文件读取响应。"""

    file_status: Literal["pending", "ready"] = Field(description="训练输出文件状态")
    task_state: str = Field(description="当前训练任务状态")
    object_key: str | None = Field(default=None, description="训练输出文件 object key")
    payload: dict[str, object] = Field(default_factory=dict, description="JSON 文件内容；未生成时为空对象")


class DetectionTrainingOutputFileSummaryResponse(BaseModel):
    """描述单个训练输出文件的读取状态。"""

    file_name: DetectionTrainingOutputFileName = Field(description="训练输出文件名称")
    file_kind: DetectionTrainingOutputFileKind = Field(description="训练输出文件类型")
    file_status: Literal["pending", "ready"] = Field(description="训练输出文件状态")
    task_state: str = Field(description="当前训练任务状态")
    object_key: str | None = Field(default=None, description="训练输出文件 object key")
    size_bytes: int | None = Field(default=None, description="文件字节大小")
    updated_at: str | None = Field(default=None, description="最后更新时间")


class DetectionTrainingOutputFileDetailResponse(DetectionTrainingOutputFileSummaryResponse):
    """描述单个训练输出文件的读取结果。"""

    payload: dict[str, object] = Field(default_factory=dict, description="JSON 文件内容；非 JSON 或未生成时为空对象")
    text_content: str | None = Field(default=None, description="文本文件内容；非文本或未生成时为空")
    lines: list[str] = Field(default_factory=list, description="文本文件按行拆分后的内容；非文本或未生成时为空列表")


def _build_detection_training_metrics_file_response(
    output_file: DetectionTrainingOutputFileDetailResponse,
) -> DetectionTrainingMetricsFileResponse:
    """把训练 JSON 输出文件详情转换为统一 metrics 响应。"""

    return DetectionTrainingMetricsFileResponse(
        file_status=output_file.file_status,
        task_state=output_file.task_state,
        object_key=output_file.object_key,
        payload=dict(output_file.payload),
    )


def _build_detection_training_output_file_summary_response(
    output_file: DetectionTrainingOutputFileDetailResponse,
) -> DetectionTrainingOutputFileSummaryResponse:
    """把训练输出文件详情压缩成列表项响应。"""

    return DetectionTrainingOutputFileSummaryResponse(
        file_name=output_file.file_name,
        file_kind=output_file.file_kind,
        file_status=output_file.file_status,
        task_state=output_file.task_state,
        object_key=output_file.object_key,
        size_bytes=output_file.size_bytes,
        updated_at=output_file.updated_at,
    )


def _parse_detection_training_output_file_name(file_name: str) -> DetectionTrainingOutputFileName:
    """校验训练输出文件名称是否属于公开资源组。"""

    if file_name in _DETECTION_TRAINING_OUTPUT_FILE_SPECS:
        return file_name  # type: ignore[return-value]
    raise ResourceNotFoundError(
        "找不到指定的训练输出文件",
        details={"file_name": file_name},
    )


def _read_detection_training_output_file(
    *,
    task: object,
    file_name: DetectionTrainingOutputFileName,
    dataset_storage: LocalDatasetStorage,
    strict_missing: bool,
) -> DetectionTrainingOutputFileDetailResponse:
    """读取训练输出文件的状态、元数据和可读内容。"""

    task_state = task.state
    spec = _DETECTION_TRAINING_OUTPUT_FILE_SPECS[file_name]
    file_kind = spec["file_kind"]
    object_key = _resolve_detection_training_output_file_object_key(task=task, file_name=file_name)
    if object_key is None:
        if strict_missing and task_state not in {"queued", "running"}:
            raise ResourceNotFoundError(
                "当前训练任务缺少训练输出文件",
                details={"task_id": task.task_id, "file_name": file_name},
            )
        return DetectionTrainingOutputFileDetailResponse(
            file_name=file_name,
            file_kind=file_kind,  # type: ignore[arg-type]
            file_status="pending",
            task_state=task_state,
            object_key=None,
        )

    file_path = dataset_storage.resolve(object_key)
    if not file_path.is_file():
        if strict_missing and task_state not in {"queued", "running"}:
            raise ResourceNotFoundError(
                "当前训练任务缺少训练输出文件",
                details={"task_id": task.task_id, "file_name": file_name, "object_key": object_key},
            )
        return DetectionTrainingOutputFileDetailResponse(
            file_name=file_name,
            file_kind=file_kind,  # type: ignore[arg-type]
            file_status="pending",
            task_state=task_state,
            object_key=object_key,
        )

    file_stat = file_path.stat()
    updated_at = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc).isoformat()
    payload: dict[str, object] = {}
    text_content: str | None = None
    lines: list[str] = []
    if file_kind == "json":
        json_payload = dataset_storage.read_json(object_key)
        if not isinstance(json_payload, dict):
            raise ServiceConfigurationError(
                "训练输出文件内容不合法",
                details={"task_id": task.task_id, "file_name": file_name, "object_key": object_key},
            )
        payload = dict(json_payload)
    elif file_kind == "text":
        text_content = file_path.read_text(encoding="utf-8")
        lines = text_content.splitlines()

    return DetectionTrainingOutputFileDetailResponse(
        file_name=file_name,
        file_kind=file_kind,  # type: ignore[arg-type]
        file_status="ready",
        task_state=task_state,
        object_key=object_key,
        size_bytes=file_stat.st_size,
        updated_at=updated_at,
        payload=payload,
        text_content=text_content,
        lines=lines,
    )


def _resolve_detection_training_output_file_object_key(
    *,
    task: object,
    file_name: DetectionTrainingOutputFileName,
) -> str | None:
    """解析训练输出文件当前可用的 object key。"""

    result = dict(task.result)
    metadata = dict(task.metadata)
    training_summary = result.get("summary")
    training_summary_payload = dict(training_summary) if isinstance(training_summary, dict) else {}
    spec = _DETECTION_TRAINING_OUTPUT_FILE_SPECS[file_name]
    object_key_field = spec["object_key_field"]
    resolved_object_key = (
        _read_optional_str(result, object_key_field)
        or _read_optional_str(metadata, object_key_field)
        or _read_optional_str(training_summary_payload, object_key_field)
    )
    if resolved_object_key is not None:
        return resolved_object_key
    output_object_prefix = (
        _read_optional_str(result, "output_object_prefix")
        or _read_optional_str(metadata, "output_object_prefix")
        or _read_optional_str(training_summary_payload, "output_object_prefix")
    )
    if output_object_prefix is None:
        return None
    return f"{output_object_prefix}/{spec['relative_path']}"


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
