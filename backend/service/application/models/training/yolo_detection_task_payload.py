"""YOLO detection 训练任务 payload 组装工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.detection_training_rules import (
    DetectionTrainingOutputFiles,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.domain.tasks.task_records import TaskRecord


def build_yolo_detection_create_task_metadata(
    *,
    dataset_export: DatasetExport,
    model_name: str,
) -> dict[str, object]:
    """构建创建训练任务时写入 TaskRecord.metadata 的字段。

    - dataset_export：训练输入使用的 DatasetExport。
    - model_name：模型类型名称。
    """

    return {
        "dataset_export_id": dataset_export.dataset_export_id,
        "dataset_export_manifest_key": dataset_export.manifest_object_key,
        "dataset_id": dataset_export.dataset_id,
        "dataset_version_id": dataset_export.dataset_version_id,
        "format_id": dataset_export.format_id,
        "model_type": model_name,
        "task_type": DETECTION_TASK_TYPE,
    }


def build_yolo_detection_queue_metadata(
    *,
    project_id: str,
    dataset_export: DatasetExport,
    model_name: str,
) -> dict[str, object]:
    """构建训练任务入队 metadata。

    - project_id：项目 id。
    - dataset_export：训练输入使用的 DatasetExport。
    - model_name：模型类型名称。
    """

    return {
        "project_id": project_id,
        "dataset_export_id": dataset_export.dataset_export_id,
        "dataset_export_manifest_key": dataset_export.manifest_object_key,
        "dataset_version_id": dataset_export.dataset_version_id,
        "format_id": dataset_export.format_id,
        "model_type": model_name,
    }


def build_yolo_detection_task_spec_payload(
    *,
    task_spec: Any,
    model_name: str,
) -> dict[str, object]:
    """把模型专属 task spec 对象转换成稳定字典。

    - task_spec：模型服务构造的 task spec 对象。
    - model_name：模型类型名称。
    """

    return {
        "project_id": task_spec.project_id,
        "dataset_export_id": task_spec.dataset_export_id,
        "dataset_export_manifest_key": task_spec.dataset_export_manifest_key,
        "manifest_object_key": task_spec.manifest_object_key,
        "recipe_id": task_spec.recipe_id,
        "model_scale": task_spec.model_scale,
        "output_model_name": task_spec.output_model_name,
        "warm_start_model_version_id": task_spec.warm_start_model_version_id,
        "evaluation_interval": task_spec.evaluation_interval,
        "max_epochs": task_spec.max_epochs,
        "batch_size": task_spec.batch_size,
        "gpu_count": task_spec.gpu_count,
        "precision": task_spec.precision,
        "input_size": list(task_spec.input_size)
        if task_spec.input_size is not None
        else None,
        "extra_options": dict(task_spec.extra_options),
        "model_type": model_name,
        "task_type": DETECTION_TASK_TYPE,
    }


def build_yolo_detection_request_kwargs_from_task_record(
    task_record: TaskRecord,
) -> dict[str, object]:
    """从 TaskRecord 还原训练请求参数。

    - task_record：训练任务记录。
    - 返回值：可传给 request class 的 kwargs。
    """

    task_spec = dict(task_record.task_spec)
    raw_input_size = task_spec.get("input_size")
    input_size = None
    if isinstance(raw_input_size, list | tuple) and len(raw_input_size) == 2:
        input_size = (int(raw_input_size[0]), int(raw_input_size[1]))
    extra_options = task_spec.get("extra_options")
    return {
        "project_id": str(task_spec.get("project_id") or task_record.project_id),
        "dataset_export_id": _read_optional_str(task_spec.get("dataset_export_id")),
        "dataset_export_manifest_key": _read_optional_str(
            task_spec.get("dataset_export_manifest_key")
        ),
        "recipe_id": str(task_spec.get("recipe_id") or ""),
        "model_scale": str(task_spec.get("model_scale") or ""),
        "output_model_name": str(task_spec.get("output_model_name") or ""),
        "warm_start_model_version_id": _read_optional_str(
            task_spec.get("warm_start_model_version_id")
        ),
        "evaluation_interval": _read_optional_int(task_spec.get("evaluation_interval")),
        "max_epochs": _read_optional_int(task_spec.get("max_epochs")),
        "batch_size": _read_optional_int(task_spec.get("batch_size")),
        "gpu_count": _read_optional_int(task_spec.get("gpu_count")),
        "precision": _read_optional_str(task_spec.get("precision")),
        "input_size": input_size,
        "extra_options": dict(extra_options) if isinstance(extra_options, dict) else {},
    }


def build_yolo_detection_existing_result_kwargs(
    task_record: TaskRecord,
) -> dict[str, object] | None:
    """从已保存的 TaskRecord.result 重建训练结果参数。

    - task_record：训练任务记录。
    - 返回值：可传给 task result class 的 kwargs；字段不足时返回 None。
    """

    result = dict(task_record.result)
    required_fields = (
        "dataset_export_id",
        "dataset_export_manifest_key",
        "dataset_version_id",
        "format_id",
        "output_object_prefix",
        "checkpoint_object_key",
    )
    if not all(
        isinstance(result.get(field_name), str) for field_name in required_fields
    ):
        return None
    return {
        "task_id": task_record.task_id,
        "status": str(result.get("status") or task_record.state),
        "dataset_export_id": str(result["dataset_export_id"]),
        "dataset_export_manifest_key": str(result["dataset_export_manifest_key"]),
        "dataset_version_id": str(result["dataset_version_id"]),
        "format_id": str(result["format_id"]),
        "output_object_prefix": str(result["output_object_prefix"]),
        "checkpoint_object_key": str(result["checkpoint_object_key"]),
        "latest_checkpoint_object_key": _read_optional_str(
            result.get("latest_checkpoint_object_key")
        ),
        "labels_object_key": _read_optional_str(result.get("labels_object_key")),
        "metrics_object_key": _read_optional_str(result.get("metrics_object_key")),
        "validation_metrics_object_key": _read_optional_str(
            result.get("validation_metrics_object_key")
        ),
        "summary_object_key": _read_optional_str(result.get("summary_object_key")),
        "best_metric_name": _read_optional_str(result.get("best_metric_name")),
        "best_metric_value": _read_optional_float(result.get("best_metric_value")),
        "summary": dict(result.get("summary") or {}),
    }


def build_yolo_detection_partial_result_kwargs(
    *,
    task_id: str,
    dataset_export: DatasetExport,
    output_files: DetectionTrainingOutputFiles,
    status: str,
    best_metric_name: str | None,
    best_metric_value: float | None,
    summary: dict[str, object],
) -> dict[str, object]:
    """根据当前任务快照构建训练结果参数。

    - task_id：训练任务 id。
    - dataset_export：训练输入使用的 DatasetExport。
    - output_files：训练输出文件路径集合。
    - status：训练结果状态。
    - best_metric_name：当前最佳指标名称。
    - best_metric_value：当前最佳指标值。
    - summary：训练摘要。
    """

    return {
        "task_id": task_id,
        "status": status,
        "dataset_export_id": dataset_export.dataset_export_id,
        "dataset_export_manifest_key": dataset_export.manifest_object_key or "",
        "dataset_version_id": dataset_export.dataset_version_id,
        "format_id": dataset_export.format_id,
        "output_object_prefix": output_files.output_object_prefix,
        "checkpoint_object_key": output_files.checkpoint_object_key,
        "latest_checkpoint_object_key": output_files.latest_checkpoint_object_key,
        "labels_object_key": output_files.labels_object_key,
        "metrics_object_key": output_files.metrics_object_key,
        "validation_metrics_object_key": output_files.validation_metrics_object_key,
        "summary_object_key": output_files.summary_object_key,
        "best_metric_name": best_metric_name,
        "best_metric_value": best_metric_value,
        "summary": summary,
    }


def build_yolo_detection_output_files_summary(
    output_files: DetectionTrainingOutputFiles,
) -> dict[str, object]:
    """把训练输出文件路径集合转换成 summary 中的 output_files 字段。"""

    return {
        "output_object_prefix": output_files.output_object_prefix,
        "checkpoint_object_key": output_files.checkpoint_object_key,
        "latest_checkpoint_object_key": output_files.latest_checkpoint_object_key,
        "labels_object_key": output_files.labels_object_key,
        "metrics_object_key": output_files.metrics_object_key,
        "validation_metrics_object_key": output_files.validation_metrics_object_key,
        "summary_object_key": output_files.summary_object_key,
    }


def serialize_yolo_detection_training_task_result(
    task_result: Any,
) -> dict[str, object]:
    """把训练结果对象转成可保存到 TaskRecord.result 的字典。

    - task_result：训练结果对象。
    """

    summary = dict(task_result.summary)
    return {
        "status": task_result.status,
        "dataset_export_id": task_result.dataset_export_id,
        "dataset_export_manifest_key": task_result.dataset_export_manifest_key,
        "dataset_version_id": task_result.dataset_version_id,
        "format_id": task_result.format_id,
        "output_object_prefix": task_result.output_object_prefix,
        "checkpoint_object_key": task_result.checkpoint_object_key,
        "latest_checkpoint_object_key": task_result.latest_checkpoint_object_key,
        "labels_object_key": task_result.labels_object_key,
        "metrics_object_key": task_result.metrics_object_key,
        "validation_metrics_object_key": task_result.validation_metrics_object_key,
        "summary_object_key": task_result.summary_object_key,
        "best_metric_name": task_result.best_metric_name,
        "best_metric_value": task_result.best_metric_value,
        "summary": summary,
        "model_version_id": _read_optional_str(summary.get("model_version_id")),
    }


def _read_optional_str(value: object) -> str | None:
    """读取可选字符串字段。"""

    if isinstance(value, str) and value.strip():
        return value
    return None


def _read_optional_int(value: object) -> int | None:
    """读取可选整数字段。"""

    if isinstance(value, int):
        return value
    return None


def _read_optional_float(value: object) -> float | None:
    """读取可选浮点数字段。"""

    if isinstance(value, int | float):
        return float(value)
    return None
