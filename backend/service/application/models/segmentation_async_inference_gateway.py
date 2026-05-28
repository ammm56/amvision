"""segmentation 公共 async inference gateway 边界。"""

from __future__ import annotations

from backend.service.application.models.detection_async_inference_gateway import (
    DETECTION_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX as SEGMENTATION_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX,
    DETECTION_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX as SEGMENTATION_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX,
    DetectionAsyncInferenceExecutor as SegmentationAsyncInferenceExecutor,
    DetectionAsyncInferenceGatewayDispatcher as SegmentationAsyncInferenceGatewayDispatcher,
    DetectionAsyncInferenceGatewayDispatcherRegistry as SegmentationAsyncInferenceGatewayDispatcherRegistry,
    QueueBackedDetectionAsyncInferenceClient as QueueBackedSegmentationAsyncInferenceClient,
    build_detection_async_inference_gateway_queue_name as build_segmentation_async_inference_gateway_queue_name,
    deserialize_detection_async_inference_execution_result_payload as deserialize_segmentation_async_inference_execution_result_payload,
    normalize_detection_async_inference_deployment_id as normalize_segmentation_async_inference_deployment_id,
    normalize_detection_async_inference_owner_id as normalize_segmentation_async_inference_owner_id,
    serialize_detection_async_inference_execution_result as serialize_segmentation_async_inference_execution_result,
)

__all__ = [
    "SEGMENTATION_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX",
    "SEGMENTATION_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX",
    "SegmentationAsyncInferenceExecutor",
    "QueueBackedSegmentationAsyncInferenceClient",
    "SegmentationAsyncInferenceGatewayDispatcher",
    "SegmentationAsyncInferenceGatewayDispatcherRegistry",
    "build_segmentation_async_inference_gateway_queue_name",
    "normalize_segmentation_async_inference_owner_id",
    "normalize_segmentation_async_inference_deployment_id",
    "serialize_segmentation_async_inference_execution_result",
    "deserialize_segmentation_async_inference_execution_result_payload",
]
