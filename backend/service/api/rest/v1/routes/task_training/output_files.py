"""非 detection 训练输出文件读取 helper。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from backend.service.application.errors import ResourceNotFoundError, ServiceConfigurationError
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


TrainingOutputFileName = Literal[
    "train-metrics",
    "validation-metrics",
    "summary",
    "labels",
    "best-checkpoint",
    "latest-checkpoint",
]
TrainingOutputFileKind = Literal["json", "text", "checkpoint"]

_TRAINING_OUTPUT_FILE_SPECS: dict[TrainingOutputFileName, dict[str, str]] = {
    "train-metrics": {
        "object_key_field": "metrics_object_key",
        "relative_path": "output-files/train-metrics.json",
        "file_kind": "json",
    },
    "validation-metrics": {
        "object_key_field": "validation_metrics_object_key",
        "relative_path": "output-files/validation-metrics.json",
        "file_kind": "json",
    },
    "summary": {
        "object_key_field": "summary_object_key",
        "relative_path": "output-files/training-summary.json",
        "file_kind": "json",
    },
    "labels": {
        "object_key_field": "labels_object_key",
        "relative_path": "output-files/labels.txt",
        "file_kind": "text",
    },
    "best-checkpoint": {
        "object_key_field": "checkpoint_object_key",
        "relative_path": "output-files/best-checkpoint.pt",
        "file_kind": "checkpoint",
    },
    "latest-checkpoint": {
        "object_key_field": "latest_checkpoint_object_key",
        "relative_path": "output-files/latest-checkpoint.pt",
        "file_kind": "checkpoint",
    },
}

_TRAINING_OUTPUT_FILE_ORDER: tuple[TrainingOutputFileName, ...] = (
    "train-metrics",
    "validation-metrics",
    "summary",
    "labels",
    "best-checkpoint",
    "latest-checkpoint",
)


class TrainingOutputFileSummaryResponse(BaseModel):
    """描述训练输出文件列表项。"""

    file_name: TrainingOutputFileName = Field(description="训练输出文件名称")
    file_kind: TrainingOutputFileKind = Field(description="训练输出文件类型")
    file_status: Literal["pending", "ready"] = Field(description="训练输出文件状态")
    task_state: str = Field(description="当前训练任务状态")
    object_key: str | None = Field(default=None, description="训练输出文件 object key")
    size_bytes: int | None = Field(default=None, description="文件字节大小")
    updated_at: str | None = Field(default=None, description="最后更新时间")


class TrainingOutputFileDetailResponse(TrainingOutputFileSummaryResponse):
    """描述单个训练输出文件读取结果。"""

    payload: dict[str, object] = Field(
        default_factory=dict,
        description="JSON 文件内容；非 JSON 或未生成时为空对象",
    )
    text_content: str | None = Field(default=None, description="文本文件内容")
    lines: list[str] = Field(
        default_factory=list,
        description="文本文件按行拆分后的内容",
    )


def list_training_output_files(
    *,
    task: TaskRecord,
    dataset_storage: LocalDatasetStorage,
) -> list[TrainingOutputFileSummaryResponse]:
    """列出非 detection 训练任务公开输出文件。"""

    return [
        _to_summary(
            read_training_output_file_detail(
                task=task,
                dataset_storage=dataset_storage,
                file_name=file_name,
                strict_missing=False,
            )
        )
        for file_name in _TRAINING_OUTPUT_FILE_ORDER
    ]


def read_training_output_file_detail(
    *,
    task: TaskRecord,
    dataset_storage: LocalDatasetStorage,
    file_name: str,
    strict_missing: bool = True,
) -> TrainingOutputFileDetailResponse:
    """读取非 detection 训练输出文件状态和内容。"""

    parsed_name = _parse_training_output_file_name(file_name)
    spec = _TRAINING_OUTPUT_FILE_SPECS[parsed_name]
    file_kind = spec["file_kind"]
    object_key = _resolve_training_output_file_object_key(task=task, file_name=parsed_name)
    if object_key is None:
        if strict_missing and task.state not in {"queued", "running"}:
            raise ResourceNotFoundError(
                "当前训练任务缺少训练输出文件",
                details={"task_id": task.task_id, "file_name": parsed_name},
            )
        return TrainingOutputFileDetailResponse(
            file_name=parsed_name,
            file_kind=file_kind,  # type: ignore[arg-type]
            file_status="pending",
            task_state=task.state,
            object_key=None,
        )

    file_path = dataset_storage.resolve(object_key)
    if not file_path.is_file():
        if strict_missing and task.state not in {"queued", "running"}:
            raise ResourceNotFoundError(
                "当前训练任务缺少训练输出文件",
                details={
                    "task_id": task.task_id,
                    "file_name": parsed_name,
                    "object_key": object_key,
                },
            )
        return TrainingOutputFileDetailResponse(
            file_name=parsed_name,
            file_kind=file_kind,  # type: ignore[arg-type]
            file_status="pending",
            task_state=task.state,
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
                details={
                    "task_id": task.task_id,
                    "file_name": parsed_name,
                    "object_key": object_key,
                },
            )
        payload = dict(json_payload)
    elif file_kind == "text":
        text_content = file_path.read_text(encoding="utf-8")
        lines = text_content.splitlines()

    return TrainingOutputFileDetailResponse(
        file_name=parsed_name,
        file_kind=file_kind,  # type: ignore[arg-type]
        file_status="ready",
        task_state=task.state,
        object_key=object_key,
        size_bytes=file_stat.st_size,
        updated_at=updated_at,
        payload=payload,
        text_content=text_content,
        lines=lines,
    )


def _to_summary(
    detail: TrainingOutputFileDetailResponse,
) -> TrainingOutputFileSummaryResponse:
    """把输出文件详情压缩成列表项。"""

    return TrainingOutputFileSummaryResponse(
        file_name=detail.file_name,
        file_kind=detail.file_kind,
        file_status=detail.file_status,
        task_state=detail.task_state,
        object_key=detail.object_key,
        size_bytes=detail.size_bytes,
        updated_at=detail.updated_at,
    )


def _parse_training_output_file_name(file_name: str) -> TrainingOutputFileName:
    """校验训练输出文件名称。"""

    if file_name in _TRAINING_OUTPUT_FILE_SPECS:
        return file_name  # type: ignore[return-value]
    raise ResourceNotFoundError(
        "找不到指定的训练输出文件",
        details={"file_name": file_name},
    )


def _resolve_training_output_file_object_key(
    *,
    task: TaskRecord,
    file_name: TrainingOutputFileName,
) -> str | None:
    """从任务快照、summary 和标准目录解析输出文件 object key。"""

    result = dict(task.result) if task.result else {}
    metadata = dict(task.metadata) if task.metadata else {}
    summary = result.get("summary")
    summary_payload = dict(summary) if isinstance(summary, dict) else {}
    summary_output_files = summary_payload.get("output_files")
    summary_output_files_payload = (
        dict(summary_output_files) if isinstance(summary_output_files, dict) else {}
    )
    result_output_files = result.get("output_files")
    result_output_files_payload = (
        dict(result_output_files) if isinstance(result_output_files, dict) else {}
    )
    spec = _TRAINING_OUTPUT_FILE_SPECS[file_name]
    object_key_field = spec["object_key_field"]
    resolved_object_key = (
        _read_optional_str(result.get(object_key_field))
        or _read_optional_str(metadata.get(object_key_field))
        or _read_optional_str(summary_payload.get(object_key_field))
        or _read_optional_str(summary_output_files_payload.get(object_key_field))
        or _read_optional_str(result_output_files_payload.get(object_key_field))
    )
    if resolved_object_key is not None:
        return resolved_object_key

    output_object_prefix = (
        _read_optional_str(result.get("output_object_prefix"))
        or _read_optional_str(result.get("output_prefix"))
        or _read_optional_str(metadata.get("output_object_prefix"))
        or _read_optional_str(summary_payload.get("output_prefix"))
        or _read_optional_str(summary_payload.get("output_object_prefix"))
        or _read_optional_str(summary_output_files_payload.get("output_object_prefix"))
        or _read_optional_str(result_output_files_payload.get("output_object_prefix"))
    )
    if output_object_prefix is None:
        return None
    return f"{output_object_prefix}/{spec['relative_path']}"


def _read_optional_str(value: object) -> str | None:
    """读取可选字符串。"""

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "TrainingOutputFileDetailResponse",
    "TrainingOutputFileSummaryResponse",
    "list_training_output_files",
    "read_training_output_file_detail",
]
