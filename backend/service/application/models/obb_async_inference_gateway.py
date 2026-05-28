"""obb 公共 async inference gateway 边界。"""

from __future__ import annotations

from backend.service.application.models.detection_async_inference_gateway import (
    DETECTION_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX as OBB_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX,
    DETECTION_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX as OBB_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX,
    DetectionAsyncInferenceExecutor as ObbAsyncInferenceExecutor,
    DetectionAsyncInferenceGatewayDispatcher as ObbAsyncInferenceGatewayDispatcher,
    DetectionAsyncInferenceGatewayDispatcherRegistry as ObbAsyncInferenceGatewayDispatcherRegistry,
    QueueBackedDetectionAsyncInferenceClient as QueueBackedObbAsyncInferenceClient,
    build_detection_async_inference_gateway_queue_name as build_obb_async_inference_gateway_queue_name,
    deserialize_detection_async_inference_execution_result_payload as deserialize_obb_async_inference_execution_result_payload,
    normalize_detection_async_inference_deployment_id as normalize_obb_async_inference_deployment_id,
    normalize_detection_async_inference_owner_id as normalize_obb_async_inference_owner_id,
    serialize_detection_async_inference_execution_result as serialize_obb_async_inference_execution_result,
)

__all__ = [
    "OBB_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX",
    "OBB_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX",
    "ObbAsyncInferenceExecutor",
    "QueueBackedObbAsyncInferenceClient",
    "ObbAsyncInferenceGatewayDispatcher",
    "ObbAsyncInferenceGatewayDispatcherRegistry",
    "build_obb_async_inference_gateway_queue_name",
    "normalize_obb_async_inference_owner_id",
    "normalize_obb_async_inference_deployment_id",
    "serialize_obb_async_inference_execution_result",
    "deserialize_obb_async_inference_execution_result_payload",
]
