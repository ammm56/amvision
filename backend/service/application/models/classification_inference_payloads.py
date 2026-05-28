"""classification 推理输入归一化与结果载荷公共入口。"""

from __future__ import annotations

from backend.service.application.models.detection_inference_payloads import (
    DETECTION_INFERENCE_INPUT_SOURCE_BASE64 as CLASSIFICATION_INFERENCE_INPUT_SOURCE_BASE64,
    DETECTION_INFERENCE_INPUT_SOURCE_FILE_ID as CLASSIFICATION_INFERENCE_INPUT_SOURCE_FILE_ID,
    DETECTION_INFERENCE_INPUT_SOURCE_MULTIPART as CLASSIFICATION_INFERENCE_INPUT_SOURCE_MULTIPART,
    DETECTION_INFERENCE_INPUT_SOURCE_URI as CLASSIFICATION_INFERENCE_INPUT_SOURCE_URI,
    DETECTION_INFERENCE_INPUT_TRANSPORT_MEMORY as CLASSIFICATION_INFERENCE_INPUT_TRANSPORT_MEMORY,
    DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE as CLASSIFICATION_INFERENCE_INPUT_TRANSPORT_STORAGE,
    DetectionInferenceInputSource as ClassificationInferenceInputSource,
    DetectionInferencePayload as ClassificationInferencePayload,
    DetectionNormalizedInferenceInput as ClassificationNormalizedInferenceInput,
    attach_detection_inference_serialize_timing as attach_classification_inference_serialize_timing,
    build_detection_inference_payload as build_classification_inference_payload,
    build_detection_prediction_request as build_classification_prediction_request,
    deserialize_detection_normalized_inference_input as deserialize_classification_normalized_inference_input,
    normalize_detection_inference_input as normalize_classification_inference_input,
    serialize_detection_inference_payload as serialize_classification_inference_payload,
    serialize_detection_normalized_inference_input as serialize_classification_normalized_inference_input,
)

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
    "build_classification_prediction_request",
    "ClassificationInferencePayload",
    "normalize_classification_inference_input",
    "build_classification_inference_payload",
    "serialize_classification_inference_payload",
    "attach_classification_inference_serialize_timing",
]
