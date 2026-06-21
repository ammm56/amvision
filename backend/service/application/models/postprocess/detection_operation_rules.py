"""detection 公共操作结果规则。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class DetectionConversionOutputFiles:
    """描述 conversion 任务产物文件布局。"""

    output_object_prefix: str
    plan_object_key: str
    report_object_key: str


@dataclass(frozen=True)
class DetectionInferenceOutputFiles:
    """描述 inference 任务产物文件布局。"""

    output_object_prefix: str
    result_object_key: str
    preview_image_object_key: str | None = None


def build_detection_conversion_output_files_payload(
    output_files: DetectionConversionOutputFiles,
) -> dict[str, object]:
    """把 conversion 产物布局转成稳定字典。"""

    return {
        "output_object_prefix": output_files.output_object_prefix,
        "plan_object_key": output_files.plan_object_key,
        "report_object_key": output_files.report_object_key,
    }


def build_detection_inference_output_files_payload(
    output_files: DetectionInferenceOutputFiles,
) -> dict[str, object]:
    """把 inference 产物布局转成稳定字典。"""

    return {
        "output_object_prefix": output_files.output_object_prefix,
        "result_object_key": output_files.result_object_key,
        "preview_image_object_key": output_files.preview_image_object_key,
    }


def build_detection_conversion_report_summary(
    *,
    phase: str,
    source_model_version_id: str,
    source_checkpoint_uri: str | None,
    model_name: str,
    model_scale: str,
    input_size: Sequence[int],
    label_count: int,
    requested_target_formats: Sequence[str],
    planned_target_formats: Sequence[str],
    executed_step_kinds: Sequence[str],
    conversion_options: dict[str, object],
    validation_summary: dict[str, object],
    outputs: Sequence[dict[str, object]],
    builds: Sequence[dict[str, object]],
    output_files: DetectionConversionOutputFiles,
) -> dict[str, object]:
    """构建 detection conversion 公共报告摘要。"""

    return {
        "phase": phase,
        "source_model_version_id": source_model_version_id,
        "source_checkpoint_uri": source_checkpoint_uri,
        "model_name": model_name,
        "model_scale": model_scale,
        "input_size": [int(item) for item in input_size],
        "label_count": int(label_count),
        "requested_target_formats": [str(item) for item in requested_target_formats],
        "planned_target_formats": [str(item) for item in planned_target_formats],
        "executed_step_kinds": [str(item) for item in executed_step_kinds],
        "conversion_options": dict(conversion_options),
        "validation_summary": dict(validation_summary),
        "outputs": [dict(item) for item in outputs],
        "builds": [dict(item) for item in builds],
        "output_files": build_detection_conversion_output_files_payload(output_files),
    }


def build_detection_inference_result_summary(
    *,
    deployment_instance_id: str,
    instance_id: str | None,
    model_version_id: str,
    model_build_id: str | None,
    input_uri: str,
    input_source_kind: str,
    score_threshold: float,
    save_result_image: bool,
    return_preview_image_base64: bool,
    detection_count: int,
    latency_ms: float | None,
    output_files: DetectionInferenceOutputFiles,
) -> dict[str, object]:
    """构建 detection inference 公共结果摘要。"""

    return {
        "deployment_instance_id": deployment_instance_id,
        "instance_id": instance_id,
        "model_version_id": model_version_id,
        "model_build_id": model_build_id,
        "input_uri": input_uri,
        "input_source_kind": input_source_kind,
        "score_threshold": float(score_threshold),
        "save_result_image": bool(save_result_image),
        "return_preview_image_base64": bool(return_preview_image_base64),
        "detection_count": int(detection_count),
        "latency_ms": float(latency_ms) if isinstance(latency_ms, int | float) else None,
        "output_files": build_detection_inference_output_files_payload(output_files),
    }


def build_detection_deployment_runtime_summary(
    *,
    model_type: str,
    model_version_id: str,
    model_build_id: str | None,
    model_name: str,
    model_scale: str,
    task_type: str,
    runtime_backend: str,
    runtime_precision: str,
    device_name: str,
    runtime_execution_mode: str,
    input_size: Sequence[int],
    label_count: int,
    instance_count: int,
) -> dict[str, object]:
    """构建长期运行 deployment 的统一运行时摘要。"""

    return {
        "model_type": model_type,
        "model_version_id": model_version_id,
        "model_build_id": model_build_id,
        "model_name": model_name,
        "model_scale": model_scale,
        "task_type": task_type,
        "runtime_backend": runtime_backend,
        "runtime_precision": runtime_precision,
        "device_name": device_name,
        "runtime_execution_mode": runtime_execution_mode,
        "input_size": [int(item) for item in input_size],
        "label_count": int(label_count),
        "instance_count": int(instance_count),
    }
