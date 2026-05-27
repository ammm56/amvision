"""detection 推理输入归一化与结果载荷公共入口。"""

from __future__ import annotations

from backend.service.application.models.yolox_inference_payloads import (
    YOLOX_INFERENCE_INPUT_SOURCE_BASE64 as DETECTION_INFERENCE_INPUT_SOURCE_BASE64,
    YOLOX_INFERENCE_INPUT_SOURCE_FILE_ID as DETECTION_INFERENCE_INPUT_SOURCE_FILE_ID,
    YOLOX_INFERENCE_INPUT_SOURCE_MULTIPART as DETECTION_INFERENCE_INPUT_SOURCE_MULTIPART,
    YOLOX_INFERENCE_INPUT_SOURCE_URI as DETECTION_INFERENCE_INPUT_SOURCE_URI,
    YOLOX_INFERENCE_INPUT_TRANSPORT_MEMORY as DETECTION_INFERENCE_INPUT_TRANSPORT_MEMORY,
    YOLOX_INFERENCE_INPUT_TRANSPORT_STORAGE as DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE,
    YoloXInferenceInputSource as DetectionInferenceInputSource,
    YoloXInferencePayload as DetectionInferencePayload,
    YoloXNormalizedInferenceInput as DetectionNormalizedInferenceInput,
    attach_yolox_inference_serialize_timing as attach_detection_inference_serialize_timing,
    build_yolox_inference_payload as build_detection_inference_payload,
    build_yolox_prediction_request as build_detection_prediction_request,
    deserialize_yolox_normalized_inference_input as deserialize_detection_normalized_inference_input,
    normalize_yolox_inference_input as normalize_detection_inference_input,
    serialize_yolox_inference_payload as serialize_detection_inference_payload,
    serialize_yolox_normalized_inference_input as serialize_detection_normalized_inference_input,
)


__all__ = [
    "DETECTION_INFERENCE_INPUT_SOURCE_URI",
    "DETECTION_INFERENCE_INPUT_SOURCE_FILE_ID",
    "DETECTION_INFERENCE_INPUT_SOURCE_BASE64",
    "DETECTION_INFERENCE_INPUT_SOURCE_MULTIPART",
    "DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE",
    "DETECTION_INFERENCE_INPUT_TRANSPORT_MEMORY",
    "DetectionInferenceInputSource",
    "DetectionNormalizedInferenceInput",
    "serialize_detection_normalized_inference_input",
    "deserialize_detection_normalized_inference_input",
    "build_detection_prediction_request",
    "DetectionInferencePayload",
    "normalize_detection_inference_input",
    "build_detection_inference_payload",
    "serialize_detection_inference_payload",
    "attach_detection_inference_serialize_timing",
]
