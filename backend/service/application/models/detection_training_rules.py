"""detection 训练操作规则与公共输出结构。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class DetectionTrainingOutputFiles:
    """描述 detection 训练产物的标准键集合。"""

    output_object_prefix: str
    checkpoint_object_key: str
    latest_checkpoint_object_key: str | None = None
    labels_object_key: str | None = None
    metrics_object_key: str | None = None
    validation_metrics_object_key: str | None = None
    summary_object_key: str | None = None


def build_detection_training_output_files_payload(
    output_files: DetectionTrainingOutputFiles,
) -> dict[str, object]:
    """把训练产物键对象转成稳定字典。"""

    return {
        "output_object_prefix": output_files.output_object_prefix,
        "checkpoint_object_key": output_files.checkpoint_object_key,
        "latest_checkpoint_object_key": output_files.latest_checkpoint_object_key,
        "labels_object_key": output_files.labels_object_key,
        "metrics_object_key": output_files.metrics_object_key,
        "validation_metrics_object_key": output_files.validation_metrics_object_key,
        "summary_object_key": output_files.summary_object_key,
    }


def build_detection_training_config_payload(
    *,
    recipe_id: str,
    model_scale: str,
    output_model_name: str,
    warm_start_model_version_id: str | None,
    evaluation_interval: int | None = None,
    max_epochs: int | None = None,
    batch_size: int | None = None,
    gpu_count: int | None = None,
    precision: str | None = None,
    input_size: Sequence[int] | None = None,
    extra_options: dict[str, object] | None = None,
) -> dict[str, object]:
    """构建 detection 训练统一配置摘要。"""

    return {
        "recipe_id": recipe_id,
        "model_scale": model_scale,
        "output_model_name": output_model_name,
        "warm_start_model_version_id": warm_start_model_version_id,
        "evaluation_interval": evaluation_interval,
        "max_epochs": max_epochs,
        "batch_size": batch_size,
        "gpu_count": gpu_count,
        "precision": precision,
        "input_size": _normalize_optional_int_list(input_size),
        "extra_options": dict(extra_options or {}),
    }


def build_detection_runtime_summary_payload(
    *,
    device: str | None,
    gpu_count: int | None,
    device_ids: Sequence[int] | None,
    precision: str | None,
    distributed_mode: bool | None,
) -> dict[str, object]:
    """构建 detection 推理与训练运行时公共摘要。"""

    return {
        "device": device,
        "gpu_count": gpu_count,
        "device_ids": _normalize_optional_int_list(device_ids) or [],
        "precision": precision,
        "distributed_mode": distributed_mode,
    }


def build_detection_metrics_summary_payload(
    *,
    best_metric_name: str | None,
    best_metric_value: float | None,
) -> dict[str, object]:
    """构建 detection 训练指标摘要。"""

    return {
        "best_metric_name": best_metric_name,
        "best_metric_value": best_metric_value,
    }


def build_detection_validation_summary_payload(
    *,
    enabled: bool,
    split_name: str | None,
    sample_count: int | None,
    evaluation_interval: int | None,
    final_metrics: dict[str, object] | None = None,
    best_metric_name: str | None = None,
    best_metric_value: float | None = None,
    evaluated_epochs: Sequence[int] | None = None,
    metrics_object_key: str | None = None,
) -> dict[str, object]:
    """构建 detection 验证摘要。"""

    return {
        "enabled": enabled,
        "split_name": split_name,
        "sample_count": sample_count,
        "evaluation_interval": evaluation_interval,
        "best_metric_name": best_metric_name,
        "best_metric_value": best_metric_value,
        "final_metrics": dict(final_metrics or {}),
        "evaluated_epochs": _normalize_optional_int_list(evaluated_epochs),
        "metrics_object_key": metrics_object_key,
    }


def build_detection_training_summary_base(
    *,
    task_id: str,
    dataset_export_id: str,
    dataset_export_manifest_key: str | None,
    dataset_version_id: str,
    format_id: str,
    recipe_id: str,
    model_scale: str,
    output_model_name: str,
    implementation_mode: str,
    sample_count: int,
    train_sample_count: int,
    split_names: Sequence[str],
    category_names: Sequence[str],
    input_size: Sequence[int],
    batch_size: int,
    max_epochs: int,
    device: str,
    gpu_count: int,
    device_ids: Sequence[int],
    distributed_mode: bool,
    requested_gpu_count: int | None,
    precision: str,
    requested_precision: str | None,
    evaluation_interval: int | None,
    parameter_count: int | None,
    best_metric_name: str | None,
    best_metric_value: float | None,
    output_files: DetectionTrainingOutputFiles,
    training_config: dict[str, object],
    validation_summary: dict[str, object],
    warm_start_summary: dict[str, object],
) -> dict[str, object]:
    """构建 detection 训练结果公共摘要基座。"""

    output_files_payload = build_detection_training_output_files_payload(output_files)
    return {
        "task_id": task_id,
        "dataset_export_id": dataset_export_id,
        "dataset_export_manifest_key": dataset_export_manifest_key,
        "manifest_object_key": dataset_export_manifest_key,
        "dataset_version_id": dataset_version_id,
        "format_id": format_id,
        "recipe_id": recipe_id,
        "model_scale": model_scale,
        "output_model_name": output_model_name,
        "implementation_mode": implementation_mode,
        "sample_count": sample_count,
        "training_sample_count": train_sample_count,
        "split_names": _normalize_str_list(split_names),
        "category_names": _normalize_str_list(category_names),
        "input_size": _normalize_required_int_list(input_size),
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "device": device,
        "gpu_count": gpu_count,
        "device_ids": _normalize_required_int_list(device_ids),
        "distributed_mode": distributed_mode,
        "requested_gpu_count": requested_gpu_count,
        "precision": precision,
        "requested_precision": requested_precision,
        "evaluation_interval": evaluation_interval,
        "parameter_count": parameter_count,
        "best_metric_name": best_metric_name,
        "best_metric_value": best_metric_value,
        "output_object_prefix": output_files.output_object_prefix,
        "checkpoint_object_key": output_files.checkpoint_object_key,
        "latest_checkpoint_object_key": output_files.latest_checkpoint_object_key,
        "labels_object_key": output_files.labels_object_key,
        "metrics_object_key": output_files.metrics_object_key,
        "validation_metrics_object_key": output_files.validation_metrics_object_key,
        "summary_object_key": output_files.summary_object_key,
        "training_config": dict(training_config),
        "validation": dict(validation_summary),
        "warm_start": dict(warm_start_summary),
        "output_files": output_files_payload,
    }


def build_detection_training_model_version_metadata(
    *,
    dataset_export_id: str,
    manifest_object_key: str | None,
    category_names: Sequence[str],
    input_size: Sequence[int] | None,
    training_config: dict[str, object],
    runtime_summary: dict[str, object],
    warm_start_summary: dict[str, object],
    registration_kind: str,
    output_files: DetectionTrainingOutputFiles,
    metrics_summary: dict[str, object],
) -> dict[str, object]:
    """构建 detection 训练输出登记到 ModelVersion 的公共 metadata。"""

    return {
        "dataset_export_id": dataset_export_id,
        "manifest_object_key": manifest_object_key,
        "category_names": _normalize_str_list(category_names),
        "input_size": _normalize_optional_int_list(input_size),
        "training_config": dict(training_config),
        "runtime_summary": dict(runtime_summary),
        "warm_start": dict(warm_start_summary),
        "registration_kind": registration_kind,
        "output_files": build_detection_training_output_files_payload(output_files),
        "metrics_summary": dict(metrics_summary),
    }


def _normalize_str_list(values: Sequence[str] | None) -> list[str]:
    """把字符串序列规整为去空白列表。"""

    if values is None:
        return []
    return [item for item in (str(value).strip() for value in values) if item]


def _normalize_optional_int_list(values: Sequence[int] | None) -> list[int] | None:
    """把可选整型序列规整为列表。"""

    if values is None:
        return None
    return [int(value) for value in values]


def _normalize_required_int_list(values: Sequence[int]) -> list[int]:
    """把必填整型序列规整为列表。"""

    return [int(value) for value in values]
