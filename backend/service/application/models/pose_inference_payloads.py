"""pose 推理输入归一化与结果载荷公共入口。"""

from __future__ import annotations

from backend.service.application.models.detection_inference_payloads import (
    DETECTION_INFERENCE_INPUT_SOURCE_BASE64 as POSE_INFERENCE_INPUT_SOURCE_BASE64,
    DETECTION_INFERENCE_INPUT_SOURCE_FILE_ID as POSE_INFERENCE_INPUT_SOURCE_FILE_ID,
    DETECTION_INFERENCE_INPUT_SOURCE_MULTIPART as POSE_INFERENCE_INPUT_SOURCE_MULTIPART,
    DETECTION_INFERENCE_INPUT_SOURCE_URI as POSE_INFERENCE_INPUT_SOURCE_URI,
    DETECTION_INFERENCE_INPUT_TRANSPORT_MEMORY as POSE_INFERENCE_INPUT_TRANSPORT_MEMORY,
    DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE as POSE_INFERENCE_INPUT_TRANSPORT_STORAGE,
    DetectionInferenceInputSource as PoseInferenceInputSource,
    DetectionInferencePayload as PoseInferencePayload,
    DetectionNormalizedInferenceInput as PoseNormalizedInferenceInput,
    attach_detection_inference_serialize_timing as attach_pose_inference_serialize_timing,
    build_detection_inference_payload as build_pose_inference_payload,
    build_detection_prediction_request as build_pose_prediction_request,
    deserialize_detection_normalized_inference_input as deserialize_pose_normalized_inference_input,
    normalize_detection_inference_input as normalize_pose_inference_input,
    serialize_detection_inference_payload as serialize_pose_inference_payload,
    serialize_detection_normalized_inference_input as serialize_pose_normalized_inference_input,
)

__all__ = [
    "POSE_INFERENCE_INPUT_SOURCE_URI",
    "POSE_INFERENCE_INPUT_SOURCE_FILE_ID",
    "POSE_INFERENCE_INPUT_SOURCE_BASE64",
    "POSE_INFERENCE_INPUT_SOURCE_MULTIPART",
    "POSE_INFERENCE_INPUT_TRANSPORT_STORAGE",
    "POSE_INFERENCE_INPUT_TRANSPORT_MEMORY",
    "PoseInferenceInputSource",
    "PoseNormalizedInferenceInput",
    "serialize_pose_normalized_inference_input",
    "deserialize_pose_normalized_inference_input",
    "build_pose_prediction_request",
    "PoseInferencePayload",
    "normalize_pose_inference_input",
    "build_pose_inference_payload",
    "serialize_pose_inference_payload",
    "attach_pose_inference_serialize_timing",
]
