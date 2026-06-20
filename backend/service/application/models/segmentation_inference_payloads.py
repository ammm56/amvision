"""segmentation 推理输入归一化与结果载荷。"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from backend.service.application.models.detection_inference_payloads import (
    DETECTION_INFERENCE_INPUT_SOURCE_BASE64 as SEGMENTATION_INFERENCE_INPUT_SOURCE_BASE64,
    DETECTION_INFERENCE_INPUT_SOURCE_FILE_ID as SEGMENTATION_INFERENCE_INPUT_SOURCE_FILE_ID,
    DETECTION_INFERENCE_INPUT_SOURCE_MULTIPART as SEGMENTATION_INFERENCE_INPUT_SOURCE_MULTIPART,
    DETECTION_INFERENCE_INPUT_SOURCE_URI as SEGMENTATION_INFERENCE_INPUT_SOURCE_URI,
    DETECTION_INFERENCE_INPUT_TRANSPORT_MEMORY as SEGMENTATION_INFERENCE_INPUT_TRANSPORT_MEMORY,
    DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE as SEGMENTATION_INFERENCE_INPUT_TRANSPORT_STORAGE,
    DetectionInferenceInputSource as SegmentationInferenceInputSource,
    DetectionNormalizedInferenceInput as SegmentationNormalizedInferenceInput,
    deserialize_detection_normalized_inference_input as deserialize_segmentation_normalized_inference_input,
    normalize_detection_inference_input as normalize_segmentation_inference_input,
    serialize_detection_normalized_inference_input as serialize_segmentation_normalized_inference_input,
)
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot
from backend.service.application.runtime.contracts.segmentation import (
    SegmentationPredictionExecutionResult,
    SegmentationPredictionRequest,
)
from backend.service.application.runtime.serialization.segmentation import (
    serialize_segmentation_instance,
    serialize_segmentation_runtime_session_info,
)


@dataclass(frozen=True)
class SegmentationInferencePayload:
    """描述 segmentation 同步直返与异步结果共用的推理结果载荷。"""

    request_id: str
    inference_task_id: str | None
    deployment_instance_id: str
    instance_id: str | None
    model_version_id: str
    model_build_id: str | None
    input_uri: str
    input_source_kind: str
    input_file_id: str | None
    score_threshold: float
    mask_threshold: float
    save_result_image: bool
    return_preview_image_base64: bool
    image_width: int
    image_height: int
    instance_count: int
    latency_ms: float | None
    decode_ms: float | None
    preprocess_ms: float | None
    infer_ms: float | None
    postprocess_ms: float | None
    serialize_ms: float | None
    labels: tuple[str, ...]
    instances: tuple[dict[str, object], ...]
    runtime_session_info: dict[str, object]
    preview_image_uri: str | None = None
    preview_image_base64: str | None = None
    result_object_key: str | None = None


def build_segmentation_prediction_request(
    *,
    normalized_input: SegmentationNormalizedInferenceInput,
    score_threshold: float,
    mask_threshold: float,
    save_result_image: bool,
    return_preview_image_base64: bool,
    extra_options: dict[str, object],
) -> SegmentationPredictionRequest:
    """把统一输入规则转换为 segmentation runtime prediction request。"""

    return SegmentationPredictionRequest(
        input_uri=(
            normalized_input.input_uri
            if normalized_input.input_transport_mode == SEGMENTATION_INFERENCE_INPUT_TRANSPORT_STORAGE
            else None
        ),
        input_image_bytes=(
            normalized_input.input_image_bytes
            if normalized_input.input_transport_mode == SEGMENTATION_INFERENCE_INPUT_TRANSPORT_MEMORY
            else None
        ),
        score_threshold=float(score_threshold),
        mask_threshold=float(mask_threshold),
        save_result_image=save_result_image or return_preview_image_base64,
        extra_options=dict(extra_options),
    )


def build_segmentation_inference_payload(
    *,
    request_id: str,
    inference_task_id: str | None,
    deployment_instance_id: str,
    instance_id: str | None,
    runtime_target: RuntimeTargetSnapshot,
    normalized_input: SegmentationNormalizedInferenceInput,
    score_threshold: float,
    mask_threshold: float,
    save_result_image: bool,
    return_preview_image_base64: bool,
    execution_result: SegmentationPredictionExecutionResult,
    preview_image_uri: str | None,
    result_object_key: str | None,
    serialize_ms: float | None = None,
) -> SegmentationInferencePayload:
    """构建 segmentation 同步直返与异步结果共用的标准载荷。"""

    preview_image_base64 = None
    if return_preview_image_base64 and execution_result.preview_image_bytes is not None:
        preview_image_base64 = base64.b64encode(execution_result.preview_image_bytes).decode("ascii")
    runtime_session_info = serialize_segmentation_runtime_session_info(
        execution_result.runtime_session_info
    )
    return SegmentationInferencePayload(
        request_id=request_id,
        inference_task_id=inference_task_id,
        deployment_instance_id=deployment_instance_id,
        instance_id=instance_id,
        model_version_id=runtime_target.model_version_id,
        model_build_id=runtime_target.model_build_id,
        input_uri=normalized_input.input_uri,
        input_source_kind=normalized_input.input_source_kind,
        input_file_id=normalized_input.input_file_id,
        score_threshold=float(score_threshold),
        mask_threshold=float(mask_threshold),
        save_result_image=save_result_image,
        return_preview_image_base64=return_preview_image_base64,
        image_width=execution_result.image_width,
        image_height=execution_result.image_height,
        instance_count=len(execution_result.instances),
        latency_ms=execution_result.latency_ms,
        decode_ms=_read_optional_timing_ms(runtime_session_info, "decode_ms"),
        preprocess_ms=_read_optional_timing_ms(runtime_session_info, "preprocess_ms"),
        infer_ms=_read_optional_timing_ms(runtime_session_info, "infer_ms"),
        postprocess_ms=_read_optional_timing_ms(runtime_session_info, "postprocess_ms"),
        serialize_ms=serialize_ms,
        labels=runtime_target.labels,
        instances=tuple(
            serialize_segmentation_instance(item)
            for item in execution_result.instances
        ),
        runtime_session_info=runtime_session_info,
        preview_image_uri=preview_image_uri,
        preview_image_base64=preview_image_base64,
        result_object_key=result_object_key,
    )


def serialize_segmentation_inference_payload(
    payload: SegmentationInferencePayload,
) -> dict[str, object]:
    """把 segmentation 推理结果载荷序列化为 JSON 字典。"""

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
        "score_threshold": payload.score_threshold,
        "mask_threshold": payload.mask_threshold,
        "save_result_image": payload.save_result_image,
        "return_preview_image_base64": payload.return_preview_image_base64,
        "image_width": payload.image_width,
        "image_height": payload.image_height,
        "instance_count": payload.instance_count,
        "latency_ms": payload.latency_ms,
        "decode_ms": payload.decode_ms,
        "preprocess_ms": payload.preprocess_ms,
        "infer_ms": payload.infer_ms,
        "postprocess_ms": payload.postprocess_ms,
        "serialize_ms": payload.serialize_ms,
        "labels": list(payload.labels),
        "instances": [dict(item) for item in payload.instances],
        "runtime_session_info": dict(payload.runtime_session_info),
        "preview_image_uri": payload.preview_image_uri,
        "preview_image_base64": payload.preview_image_base64,
        "result_object_key": payload.result_object_key,
    }


def attach_segmentation_inference_serialize_timing(
    *,
    payload: dict[str, object],
    serialize_ms: float,
) -> dict[str, object]:
    """把 segmentation 响应序列化阶段耗时写回统一推理载荷。"""

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
    "SEGMENTATION_INFERENCE_INPUT_SOURCE_URI",
    "SEGMENTATION_INFERENCE_INPUT_SOURCE_FILE_ID",
    "SEGMENTATION_INFERENCE_INPUT_SOURCE_BASE64",
    "SEGMENTATION_INFERENCE_INPUT_SOURCE_MULTIPART",
    "SEGMENTATION_INFERENCE_INPUT_TRANSPORT_STORAGE",
    "SEGMENTATION_INFERENCE_INPUT_TRANSPORT_MEMORY",
    "SegmentationInferenceInputSource",
    "SegmentationNormalizedInferenceInput",
    "serialize_segmentation_normalized_inference_input",
    "deserialize_segmentation_normalized_inference_input",
    "SegmentationInferencePayload",
    "build_segmentation_prediction_request",
    "normalize_segmentation_inference_input",
    "build_segmentation_inference_payload",
    "serialize_segmentation_inference_payload",
    "attach_segmentation_inference_serialize_timing",
]
