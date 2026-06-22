"""detection evaluation 输出文件读取 helper。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from backend.service.application.errors import ResourceNotFoundError, ServiceConfigurationError
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


DetectionEvaluationOutputFileName = Literal["report", "detections", "result-package"]
DetectionEvaluationOutputFileKind = Literal["json", "archive"]

_DETECTION_EVALUATION_OUTPUT_FILE_SPECS: dict[DetectionEvaluationOutputFileName, dict[str, str]] = {
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

_DETECTION_EVALUATION_OUTPUT_FILE_ORDER: tuple[DetectionEvaluationOutputFileName, ...] = (
    "report",
    "detections",
    "result-package",
)


class DetectionEvaluationReportResponse(BaseModel):
    """描述 detection 评估报告读取响应。"""

    file_status: Literal["pending", "ready"] = Field(description="评估报告文件状态")
    task_state: str = Field(description="当前评估任务状态")
    object_key: str | None = Field(default=None, description="评估报告 object key")
    payload: dict[str, object] = Field(default_factory=dict, description="评估报告 JSON 内容")


class DetectionEvaluationOutputFileSummaryResponse(BaseModel):
    """描述单个评估输出文件的读取状态。"""

    file_name: DetectionEvaluationOutputFileName = Field(description="评估输出文件名称")
    file_kind: DetectionEvaluationOutputFileKind = Field(description="评估输出文件类型")
    file_status: Literal["pending", "ready", "skipped"] = Field(description="评估输出文件状态")
    task_state: str = Field(description="当前评估任务状态")
    object_key: str | None = Field(default=None, description="评估输出文件 object key")
    size_bytes: int | None = Field(default=None, description="文件字节大小")
    updated_at: str | None = Field(default=None, description="最后更新时间")


def _read_detection_evaluation_report(
    *,
    task: object,
    dataset_storage: LocalDatasetStorage,
) -> DetectionEvaluationReportResponse:
    """读取 detection 评估报告。"""

    task_state = task.state
    object_key = _resolve_detection_evaluation_output_file_object_key(task=task, file_name="report")
    if object_key is None:
        if task_state not in {"queued", "running"}:
            raise ResourceNotFoundError(
                "当前评估任务缺少评估报告",
                details={"task_id": task.task_id},
            )
        return DetectionEvaluationReportResponse(file_status="pending", task_state=task_state, object_key=None)

    file_path = dataset_storage.resolve(object_key)
    if not file_path.is_file():
        if task_state not in {"queued", "running"}:
            raise ResourceNotFoundError(
                "当前评估任务缺少评估报告",
                details={"task_id": task.task_id, "object_key": object_key},
            )
        return DetectionEvaluationReportResponse(file_status="pending", task_state=task_state, object_key=object_key)

    payload = dataset_storage.read_json(object_key)
    if not isinstance(payload, dict):
        raise ServiceConfigurationError(
            "评估报告内容不合法",
            details={"task_id": task.task_id, "object_key": object_key},
        )
    return DetectionEvaluationReportResponse(
        file_status="ready",
        task_state=task_state,
        object_key=object_key,
        payload=dict(payload),
    )


def _build_detection_evaluation_output_file_summary_response(
    *,
    task: object,
    file_name: DetectionEvaluationOutputFileName,
    dataset_storage: LocalDatasetStorage,
) -> DetectionEvaluationOutputFileSummaryResponse:
    """构建单个评估输出文件的摘要响应。"""

    task_state = task.state
    spec = _DETECTION_EVALUATION_OUTPUT_FILE_SPECS[file_name]
    object_key = _resolve_detection_evaluation_output_file_object_key(task=task, file_name=file_name)
    if object_key is None:
        file_status: Literal["pending", "ready", "skipped"] = "skipped" if file_name == "result-package" else "pending"
        return DetectionEvaluationOutputFileSummaryResponse(
            file_name=file_name,
            file_kind=spec["file_kind"],  # type: ignore[arg-type]
            file_status=file_status,
            task_state=task_state,
            object_key=None,
        )

    file_path = dataset_storage.resolve(object_key)
    if not file_path.is_file():
        return DetectionEvaluationOutputFileSummaryResponse(
            file_name=file_name,
            file_kind=spec["file_kind"],  # type: ignore[arg-type]
            file_status="pending",
            task_state=task_state,
            object_key=object_key,
        )

    file_stat = file_path.stat()
    return DetectionEvaluationOutputFileSummaryResponse(
        file_name=file_name,
        file_kind=spec["file_kind"],  # type: ignore[arg-type]
        file_status="ready",
        task_state=task_state,
        object_key=object_key,
        size_bytes=file_stat.st_size,
        updated_at=datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc).isoformat(),
    )


def _resolve_detection_evaluation_output_file_object_key(
    *,
    task: object,
    file_name: DetectionEvaluationOutputFileName,
) -> str | None:
    """解析评估输出文件当前可用的 object key。"""

    result = dict(task.result)
    metadata = dict(task.metadata)
    spec = _DETECTION_EVALUATION_OUTPUT_FILE_SPECS[file_name]
    object_key_field = spec["object_key_field"]
    resolved_object_key = _read_optional_str(result, object_key_field) or _read_optional_str(metadata, object_key_field)
    if resolved_object_key is not None:
        return resolved_object_key
    output_object_prefix = _read_optional_str(result, "output_object_prefix") or _read_optional_str(metadata, "output_object_prefix")
    if output_object_prefix is None:
        return None
    return f"{output_object_prefix}/{spec['relative_path']}"


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
