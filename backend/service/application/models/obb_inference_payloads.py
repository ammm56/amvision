"""obb 推理输入归一化与结果载荷公共入口。"""

from __future__ import annotations

from backend.service.application.models.detection_inference_payloads import (
    DETECTION_INFERENCE_INPUT_SOURCE_BASE64 as OBB_INFERENCE_INPUT_SOURCE_BASE64,
    DETECTION_INFERENCE_INPUT_SOURCE_FILE_ID as OBB_INFERENCE_INPUT_SOURCE_FILE_ID,
    DETECTION_INFERENCE_INPUT_SOURCE_MULTIPART as OBB_INFERENCE_INPUT_SOURCE_MULTIPART,
    DETECTION_INFERENCE_INPUT_SOURCE_URI as OBB_INFERENCE_INPUT_SOURCE_URI,
    DETECTION_INFERENCE_INPUT_TRANSPORT_MEMORY as OBB_INFERENCE_INPUT_TRANSPORT_MEMORY,
    DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE as OBB_INFERENCE_INPUT_TRANSPORT_STORAGE,
    DetectionInferenceInputSource as ObbInferenceInputSource,
    DetectionInferencePayload as ObbInferencePayload,
    DetectionNormalizedInferenceInput as ObbNormalizedInferenceInput,
    attach_detection_inference_serialize_timing as attach_obb_inference_serialize_timing,
    build_detection_inference_payload as build_obb_inference_payload,
    build_detection_prediction_request as build_obb_prediction_request,
    deserialize_detection_normalized_inference_input as deserialize_obb_normalized_inference_input,
    normalize_detection_inference_input as normalize_obb_inference_input,
    serialize_detection_inference_payload as serialize_obb_inference_payload,
    serialize_detection_normalized_inference_input as serialize_obb_normalized_inference_input,
)

__all__ = [
    "OBB_INFERENCE_INPUT_SOURCE_URI",
    "OBB_INFERENCE_INPUT_SOURCE_FILE_ID",
    "OBB_INFERENCE_INPUT_SOURCE_BASE64",
    "OBB_INFERENCE_INPUT_SOURCE_MULTIPART",
    "OBB_INFERENCE_INPUT_TRANSPORT_STORAGE",
    "OBB_INFERENCE_INPUT_TRANSPORT_MEMORY",
    "ObbInferenceInputSource",
    "ObbNormalizedInferenceInput",
    "serialize_obb_normalized_inference_input",
    "deserialize_obb_normalized_inference_input",
    "build_obb_prediction_request",
    "ObbInferencePayload",
    "normalize_obb_inference_input",
    "build_obb_inference_payload",
    "serialize_obb_inference_payload",
    "attach_obb_inference_serialize_timing",
]
