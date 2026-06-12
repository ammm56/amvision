"""classification 推理输入归一化与结果载荷。"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from backend.service.application.models.detection_inference_payloads import (
    DETECTION_INFERENCE_INPUT_SOURCE_BASE64 as CLASSIFICATION_INFERENCE_INPUT_SOURCE_BASE64,
    DETECTION_INFERENCE_INPUT_SOURCE_FILE_ID as CLASSIFICATION_INFERENCE_INPUT_SOURCE_FILE_ID,
    DETECTION_INFERENCE_INPUT_SOURCE_MULTIPART as CLASSIFICATION_INFERENCE_INPUT_SOURCE_MULTIPART,
    DETECTION_INFERENCE_INPUT_SOURCE_URI as CLASSIFICATION_INFERENCE_INPUT_SOURCE_URI,
    DETECTION_INFERENCE_INPUT_TRANSPORT_MEMORY as CLASSIFICATION_INFERENCE_INPUT_TRANSPORT_MEMORY,
    DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE as CLASSIFICATION_INFERENCE_INPUT_TRANSPORT_STORAGE,
    DetectionInferenceInputSource as ClassificationInferenceInputSource,
    DetectionNormalizedInferenceInput as ClassificationNormalizedInferenceInput,
    deserialize_detection_normalized_inference_input as deserialize_classification_normalized_inference_input,
    normalize_detection_inference_input as normalize_classification_inference_input,
    serialize_detection_normalized_inference_input as serialize_classification_normalized_inference_input,
)
from backend.service.application.runtime.classification_runtime_contracts import (
    ClassificationPredictionExecutionResult,
    ClassificationPredictionRequest,
)
from backend.service.application.runtime.classification_runtime_serialization import (
    serialize_classification_category,
    serialize_classification_runtime_session_info,
)
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot


@dataclass(frozen=True)
class ClassificationInferencePayload:
    """描述 classification 同步直返与异步结果共用的推理结果载荷。"""

    request_id: str
    inference_task_id: str | None
    deployment_instance_id: str
    instance_id: str | None
    model_version_id: str
    model_build_id: str | None
    input_uri: str
    input_source_kind: str
    input_file_id: str | None
    top_k: int
    save_result_image: bool
    return_preview_image_base64: bool
    image_width: int
    image_height: int
    category_count: int
    latency_ms: float | None
    decode_ms: float | None
    preprocess_ms: float | None
    infer_ms: float | None
    postprocess_ms: float | None
    serialize_ms: float | None
    labels: tuple[str, ...]
    categories: tuple[dict[str, object], ...]
    top_category: dict[str, object] | None
    runtime_session_info: dict[str, object]
    preview_image_uri: str | None = None
    preview_image_base64: str | None = None
    result_object_key: str | None = None


def build_classification_prediction_request(
    *,
    normalized_input: ClassificationNormalizedInferenceInput,
    top_k: int,
    save_result_image: bool,
    return_preview_image_base64: bool,
    extra_options: dict[str, object],
) -> ClassificationPredictionRequest:
    """把统一输入规则转换为 classification runtime prediction request。"""

    return ClassificationPredictionRequest(
        input_uri=(
            normalized_input.input_uri
            if normalized_input.input_transport_mode == CLASSIFICATION_INFERENCE_INPUT_TRANSPORT_STORAGE
            else None
        ),
        input_image_bytes=(
            normalized_input.input_image_bytes
            if normalized_input.input_transport_mode == CLASSIFICATION_INFERENCE_INPUT_TRANSPORT_MEMORY
            else None
        ),
        top_k=max(1, int(top_k)),
        save_result_image=save_result_image or return_preview_image_base64,
        extra_options=dict(extra_options),
    )


def build_classification_inference_payload(
    *,
    request_id: str,
    inference_task_id: str | None,
    deployment_instance_id: str,
    instance_id: str | None,
    runtime_target: RuntimeTargetSnapshot,
    normalized_input: ClassificationNormalizedInferenceInput,
    top_k: int,
    save_result_image: bool,
    return_preview_image_base64: bool,
    execution_result: ClassificationPredictionExecutionResult,
    preview_image_uri: str | None,
    result_object_key: str | None,
    serialize_ms: float | None = None,
) -> ClassificationInferencePayload:
    """构建 classification 同步直返与异步结果共用的标准载荷。"""

    preview_image_base64 = None
    if return_preview_image_base64 and execution_result.preview_image_bytes is not None:
        preview_image_base64 = base64.b64encode(execution_result.preview_image_bytes).decode("ascii")
    runtime_session_info = serialize_classification_runtime_session_info(
        execution_result.runtime_session_info
    )
    return ClassificationInferencePayload(
        request_id=request_id,
        inference_task_id=inference_task_id,
        deployment_instance_id=deployment_instance_id,
        instance_id=instance_id,
        model_version_id=runtime_target.model_version_id,
        model_build_id=runtime_target.model_build_id,
        input_uri=normalized_input.input_uri,
        input_source_kind=normalized_input.input_source_kind,
        input_file_id=normalized_input.input_file_id,
        top_k=max(1, int(top_k)),
        save_result_image=save_result_image,
        return_preview_image_base64=return_preview_image_base64,
        image_width=execution_result.image_width,
        image_height=execution_result.image_height,
        category_count=len(execution_result.categories),
        latency_ms=execution_result.latency_ms,
        decode_ms=_read_optional_timing_ms(runtime_session_info, "decode_ms"),
        preprocess_ms=_read_optional_timing_ms(runtime_session_info, "preprocess_ms"),
        infer_ms=_read_optional_timing_ms(runtime_session_info, "infer_ms"),
        postprocess_ms=_read_optional_timing_ms(runtime_session_info, "postprocess_ms"),
        serialize_ms=serialize_ms,
        labels=runtime_target.labels,
        categories=tuple(
            serialize_classification_category(item)
            for item in execution_result.categories
        ),
        top_category=(
            serialize_classification_category(execution_result.top_category)
            if execution_result.top_category is not None
            else None
        ),
        runtime_session_info=runtime_session_info,
        preview_image_uri=preview_image_uri,
        preview_image_base64=preview_image_base64,
        result_object_key=result_object_key,
    )


def serialize_classification_inference_payload(
    payload: ClassificationInferencePayload,
) -> dict[str, object]:
    """把 classification 推理结果载荷序列化为 JSON 字典。"""

    return {
        "request_id": payload.request_id,
        "inference_task_id": payload.inference_task_id,
        "deployment_instance_id": payload.deployment_instance_id,
        "instance_id": payload.instance_id,
        "model_version_id": payload.model_version_id,
        "model_build_id": payload.model_build_id,
        "input_uri": payload.input_uri,
        "input_source_kind": payload.input_source_kind,
        "input_file_id": payload.input_file_id,
        "top_k": payload.top_k,
        "save_result_image": payload.save_result_image,
        "return_preview_image_base64": payload.return_preview_image_base64,
        "image_width": payload.image_width,
        "image_height": payload.image_height,
        "category_count": payload.category_count,
        "latency_ms": payload.latency_ms,
        "decode_ms": payload.decode_ms,
        "preprocess_ms": payload.preprocess_ms,
        "infer_ms": payload.infer_ms,
        "postprocess_ms": payload.postprocess_ms,
        "serialize_ms": payload.serialize_ms,
        "labels": list(payload.labels),
        "categories": [dict(item) for item in payload.categories],
        "top_category": dict(payload.top_category) if isinstance(payload.top_category, dict) else None,
        "runtime_session_info": dict(payload.runtime_session_info),
        "preview_image_uri": payload.preview_image_uri,
        "preview_image_base64": payload.preview_image_base64,
        "result_object_key": payload.result_object_key,
    }


def attach_classification_inference_serialize_timing(
    *,
    payload: dict[str, object],
    serialize_ms: float,
) -> dict[str, object]:
    """把 classification 响应序列化阶段耗时写回统一推理载荷。"""

    payload["serialize_ms"] = round(float(serialize_ms), 3)
    runtime_session_info = payload.get("runtime_session_info")
    if isinstance(runtime_session_info, dict):
        metadata = runtime_session_info.get("metadata")
        if isinstance(metadata, dict):
            metadata["serialize_ms"] = payload["serialize_ms"]
    return payload


def _read_optional_timing_ms(runtime_session_info: dict[str, object], key: str) -> float | None:
    """从 runtime_session_info.metadata 中读取可选阶段耗时。"""

    metadata = runtime_session_info.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


__all__ = [
    "CLASSIFICATION_INFERENCE_INPUT_SOURCE_URI",
    "CLASSIFICATION_INFERENCE_INPUT_SOURCE_FILE_ID",
    "CLASSIFICATION_INFERENCE_INPUT_SOURCE_BASE64",
    "CLASSIFICATION_INFERENCE_INPUT_SOURCE_MULTIPART",
    "CLASSIFICATION_INFERENCE_INPUT_TRANSPORT_STORAGE",
    "CLASSIFICATION_INFERENCE_INPUT_TRANSPORT_MEMORY",
    "ClassificationInferenceInputSource",
    "ClassificationNormalizedInferenceInput",
    "serialize_classification_normalized_inference_input",
    "deserialize_classification_normalized_inference_input",
    "ClassificationInferencePayload",
    "build_classification_prediction_request",
    "normalize_classification_inference_input",
    "build_classification_inference_payload",
    "serialize_classification_inference_payload",
    "attach_classification_inference_serialize_timing",
]
