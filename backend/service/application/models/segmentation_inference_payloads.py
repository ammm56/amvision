"""segmentation 推理输入归一化与结果载荷公共入口。"""

from __future__ import annotations

from backend.service.application.models.detection_inference_payloads import (
    DETECTION_INFERENCE_INPUT_SOURCE_BASE64 as SEGMENTATION_INFERENCE_INPUT_SOURCE_BASE64,
    DETECTION_INFERENCE_INPUT_SOURCE_FILE_ID as SEGMENTATION_INFERENCE_INPUT_SOURCE_FILE_ID,
    DETECTION_INFERENCE_INPUT_SOURCE_MULTIPART as SEGMENTATION_INFERENCE_INPUT_SOURCE_MULTIPART,
    DETECTION_INFERENCE_INPUT_SOURCE_URI as SEGMENTATION_INFERENCE_INPUT_SOURCE_URI,
    DETECTION_INFERENCE_INPUT_TRANSPORT_MEMORY as SEGMENTATION_INFERENCE_INPUT_TRANSPORT_MEMORY,
    DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE as SEGMENTATION_INFERENCE_INPUT_TRANSPORT_STORAGE,
    DetectionInferenceInputSource as SegmentationInferenceInputSource,
    DetectionInferencePayload as SegmentationInferencePayload,
    DetectionNormalizedInferenceInput as SegmentationNormalizedInferenceInput,
    attach_detection_inference_serialize_timing as attach_segmentation_inference_serialize_timing,
    build_detection_inference_payload as build_segmentation_inference_payload,
    build_detection_prediction_request as build_segmentation_prediction_request,
    deserialize_detection_normalized_inference_input as deserialize_segmentation_normalized_inference_input,
    normalize_detection_inference_input as normalize_segmentation_inference_input,
    serialize_detection_inference_payload as serialize_segmentation_inference_payload,
    serialize_detection_normalized_inference_input as serialize_segmentation_normalized_inference_input,
)

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
    "build_segmentation_prediction_request",
    "SegmentationInferencePayload",
    "normalize_segmentation_inference_input",
    "build_segmentation_inference_payload",
    "serialize_segmentation_inference_payload",
    "attach_segmentation_inference_serialize_timing",
]
