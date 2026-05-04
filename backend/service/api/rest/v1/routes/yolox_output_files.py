"""YOLOX 任务输出文件读取 helper。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from backend.service.application.errors import ResourceNotFoundError, ServiceConfigurationError
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YoloXTrainingOutputFileName = Literal[
    "train-metrics",
    "validation-metrics",
    "summary",
    "labels",
    "best-checkpoint",
    "latest-checkpoint",
]

YoloXTrainingOutputFileKind = Literal["json", "text", "checkpoint"]
YoloXEvaluationOutputFileName = Literal["report", "detections", "result-package"]
YoloXEvaluationOutputFileKind = Literal["json", "archive"]

_YOLOX_TRAINING_OUTPUT_FILE_SPECS: dict[YoloXTrainingOutputFileName, dict[str, str]] = {
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

_YOLOX_TRAINING_OUTPUT_FILE_ORDER: tuple[YoloXTrainingOutputFileName, ...] = (
    "train-metrics",
    "validation-metrics",
    "summary",
    "labels",
    "best-checkpoint",
    "latest-checkpoint",
)

_YOLOX_EVALUATION_OUTPUT_FILE_SPECS: dict[YoloXEvaluationOutputFileName, dict[str, str]] = {
    "report": {
        "object_key_field": "report_object_key",
        "relative_path": "artifacts/reports/evaluation-report.json",
        "file_kind": "json",
    },
    "detections": {
        "object_key_field": "detections_object_key",
        "relative_path": "artifacts/reports/detections.json",
        "file_kind": "json",
    },
    "result-package": {
        "object_key_field": "result_package_object_key",
        "relative_path": "artifacts/packages/result-package.zip",
        "file_kind": "archive",
    },
}

_YOLOX_EVALUATION_OUTPUT_FILE_ORDER: tuple[YoloXEvaluationOutputFileName, ...] = (
    "report",
    "detections",
    "result-package",
)


class YoloXTrainingMetricsFileResponse(BaseModel):
    """描述训练 JSON 输出文件读取响应。

    字段：
    - file_status：训练输出文件状态。
    - task_state：当前训练任务状态。
    - object_key：训练输出文件 object key。
    - payload：JSON 文件内容；未生成时为空对象。
    """

    file_status: Literal["pending", "ready"] = Field(description="训练输出文件状态")
    task_state: str = Field(description="当前训练任务状态")
    object_key: str | None = Field(default=None, description="训练输出文件 object key")
    payload: dict[str, object] = Field(default_factory=dict, description="JSON 文件内容；未生成时为空对象")


class YoloXTrainingOutputFileSummaryResponse(BaseModel):
    """描述单个训练输出文件的读取状态。

    字段：
    - file_name：训练输出文件名称。
    - file_kind：训练输出文件类型。
    - file_status：训练输出文件状态。
    - task_state：当前训练任务状态。
    - object_key：训练输出文件 object key。
    - size_bytes：文件字节大小。
    - updated_at：最后更新时间。
    """

    file_name: YoloXTrainingOutputFileName = Field(description="训练输出文件名称")
    file_kind: YoloXTrainingOutputFileKind = Field(description="训练输出文件类型")
    file_status: Literal["pending", "ready"] = Field(description="训练输出文件状态")
    task_state: str = Field(description="当前训练任务状态")
    object_key: str | None = Field(default=None, description="训练输出文件 object key")
    size_bytes: int | None = Field(default=None, description="文件字节大小")
    updated_at: str | None = Field(default=None, description="最后更新时间")


class YoloXTrainingOutputFileDetailResponse(YoloXTrainingOutputFileSummaryResponse):
    """描述单个训练输出文件的读取结果。

    字段：
    - payload：JSON 文件内容；非 JSON 或未生成时为空对象。
    - text_content：文本文件内容；非文本或未生成时为空。
    - lines：文本文件按行拆分后的内容；非文本或未生成时为空列表。
    """

    payload: dict[str, object] = Field(default_factory=dict, description="JSON 文件内容；非 JSON 或未生成时为空对象")
    text_content: str | None = Field(default=None, description="文本文件内容；非文本或未生成时为空")
    lines: list[str] = Field(default_factory=list, description="文本文件按行拆分后的内容；非文本或未生成时为空列表")


class YoloXEvaluationReportResponse(BaseModel):
    """描述 YOLOX 评估报告读取响应。

    字段：
    - file_status：评估报告文件状态。
    - task_state：当前评估任务状态。
    - object_key：评估报告 object key。
    - payload：评估报告 JSON 内容。
    """

    file_status: Literal["pending", "ready"] = Field(description="评估报告文件状态")
    task_state: str = Field(description="当前评估任务状态")
    object_key: str | None = Field(default=None, description="评估报告 object key")
    payload: dict[str, object] = Field(default_factory=dict, description="评估报告 JSON 内容")


class YoloXEvaluationOutputFileSummaryResponse(BaseModel):
    """描述单个评估输出文件的读取状态。

    字段：
    - file_name：评估输出文件名称。
    - file_kind：评估输出文件类型。
    - file_status：评估输出文件状态。
    - task_state：当前评估任务状态。
    - object_key：评估输出文件 object key。
    - size_bytes：文件字节大小。
    - updated_at：最后更新时间。
    """

    file_name: YoloXEvaluationOutputFileName = Field(description="评估输出文件名称")
    file_kind: YoloXEvaluationOutputFileKind = Field(description="评估输出文件类型")
    file_status: Literal["pending", "ready", "skipped"] = Field(description="评估输出文件状态")
    task_state: str = Field(description="当前评估任务状态")
    object_key: str | None = Field(default=None, description="评估输出文件 object key")
    size_bytes: int | None = Field(default=None, description="文件字节大小")
    updated_at: str | None = Field(default=None, description="最后更新时间")


def _build_yolox_training_metrics_file_response(
    output_file: YoloXTrainingOutputFileDetailResponse,
) -> YoloXTrainingMetricsFileResponse:
    """把训练 JSON 输出文件详情转换为统一 metrics 响应。"""

    return YoloXTrainingMetricsFileResponse(
        file_status=output_file.file_status,
        task_state=output_file.task_state,
        object_key=output_file.object_key,
        payload=dict(output_file.payload),
    )


def _parse_yolox_training_output_file_name(file_name: str) -> YoloXTrainingOutputFileName:
    """校验训练输出文件名称是否属于公开资源组。"""

    if file_name in _YOLOX_TRAINING_OUTPUT_FILE_SPECS:
        return file_name  # type: ignore[return-value]
    raise ResourceNotFoundError(
        "找不到指定的训练输出文件",
        details={"file_name": file_name},
    )


def _resolve_yolox_training_output_file_object_key(
    *,
    task: object,
    file_name: YoloXTrainingOutputFileName,
) -> str | None:
    """解析训练输出文件当前可用的 object key。"""

    result = dict(task.result)
    metadata = dict(task.metadata)
    training_summary = result.get("summary")
    training_summary_payload = dict(training_summary) if isinstance(training_summary, dict) else {}
    spec = _YOLOX_TRAINING_OUTPUT_FILE_SPECS[file_name]
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


def _build_yolox_training_output_file_summary_response(
    output_file: YoloXTrainingOutputFileDetailResponse,
) -> YoloXTrainingOutputFileSummaryResponse:
    """把训练输出文件详情压缩成列表项响应。"""

    return YoloXTrainingOutputFileSummaryResponse(
        file_name=output_file.file_name,
        file_kind=output_file.file_kind,
        file_status=output_file.file_status,
        task_state=output_file.task_state,
        object_key=output_file.object_key,
        size_bytes=output_file.size_bytes,
        updated_at=output_file.updated_at,
    )


def _read_yolox_training_output_file(
    *,
    task: object,
    file_name: YoloXTrainingOutputFileName,
    dataset_storage: LocalDatasetStorage,
    strict_missing: bool,
) -> YoloXTrainingOutputFileDetailResponse:
    """读取训练输出文件的状态、元数据和可读内容。"""

    task_state = task.state
    spec = _YOLOX_TRAINING_OUTPUT_FILE_SPECS[file_name]
    file_kind = spec["file_kind"]
    object_key = _resolve_yolox_training_output_file_object_key(task=task, file_name=file_name)
    if object_key is None:
        if strict_missing and task_state not in {"queued", "running"}:
            raise ResourceNotFoundError(
                "当前训练任务缺少训练输出文件",
                details={
                    "task_id": task.task_id,
                    "file_name": file_name,
                },
            )
        return YoloXTrainingOutputFileDetailResponse(
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
                details={
                    "task_id": task.task_id,
                    "file_name": file_name,
                    "object_key": object_key,
                },
            )
        return YoloXTrainingOutputFileDetailResponse(
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
                details={
                    "task_id": task.task_id,
                    "file_name": file_name,
                    "object_key": object_key,
                },
            )
        payload = dict(json_payload)
    elif file_kind == "text":
        text_content = file_path.read_text(encoding="utf-8")
        lines = text_content.splitlines()

    return YoloXTrainingOutputFileDetailResponse(
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


def _read_yolox_evaluation_report(
    *,
    task: object,
    dataset_storage: LocalDatasetStorage,
) -> YoloXEvaluationReportResponse:
    """读取 YOLOX 评估报告状态与内容。"""

    result = dict(task.result)
    object_key = _read_optional_str(result, "report_object_key")
    if object_key is None:
        if task.state in {"queued", "running"}:
            return YoloXEvaluationReportResponse(
                file_status="pending",
                task_state=task.state,
                object_key=None,
                payload={},
            )
        raise ResourceNotFoundError(
            "当前评估任务缺少 report 文件",
            details={"task_id": task.task_id},
        )
    resolved_path = dataset_storage.resolve(object_key)
    if not resolved_path.is_file():
        if task.state in {"queued", "running"}:
            return YoloXEvaluationReportResponse(
                file_status="pending",
                task_state=task.state,
                object_key=object_key,
                payload={},
            )
        raise ResourceNotFoundError(
            "当前评估任务的 report 文件不存在",
            details={"task_id": task.task_id, "object_key": object_key},
        )
    payload = dataset_storage.read_json(object_key)
    return YoloXEvaluationReportResponse(
        file_status="ready",
        task_state=task.state,
        object_key=object_key,
        payload=dict(payload) if isinstance(payload, dict) else {},
    )


def _build_yolox_evaluation_output_file_summary_response(
    *,
    task: object,
    file_name: YoloXEvaluationOutputFileName,
    dataset_storage: LocalDatasetStorage,
) -> YoloXEvaluationOutputFileSummaryResponse:
    """构建单个评估输出文件摘要。"""

    spec = _YOLOX_EVALUATION_OUTPUT_FILE_SPECS[file_name]
    result = dict(task.result)
    task_spec = dict(task.task_spec)
    object_key = _read_optional_str(result, spec["object_key_field"])
    if (
        file_name == "result-package"
        and task.state in {"succeeded", "failed", "cancelled"}
        and task_spec.get("save_result_package") is False
        and object_key is None
    ):
        return YoloXEvaluationOutputFileSummaryResponse(
            file_name=file_name,
            file_kind=spec["file_kind"],
            file_status="skipped",
            task_state=task.state,
            object_key=None,
            size_bytes=None,
            updated_at=None,
        )
    if object_key is None:
        return YoloXEvaluationOutputFileSummaryResponse(
            file_name=file_name,
            file_kind=spec["file_kind"],
            file_status="pending",
            task_state=task.state,
            object_key=None,
            size_bytes=None,
            updated_at=None,
        )
    resolved_path = dataset_storage.resolve(object_key)
    if not resolved_path.is_file():
        return YoloXEvaluationOutputFileSummaryResponse(
            file_name=file_name,
            file_kind=spec["file_kind"],
            file_status="pending",
            task_state=task.state,
            object_key=object_key,
            size_bytes=None,
            updated_at=None,
        )
    stat_result = resolved_path.stat()
    updated_at = datetime.fromtimestamp(stat_result.st_mtime, timezone.utc).isoformat()
    return YoloXEvaluationOutputFileSummaryResponse(
        file_name=file_name,
        file_kind=spec["file_kind"],
        file_status="ready",
        task_state=task.state,
        object_key=object_key,
        size_bytes=stat_result.st_size,
        updated_at=updated_at,
    )


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None