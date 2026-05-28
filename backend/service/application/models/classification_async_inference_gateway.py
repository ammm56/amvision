"""classification 公共 async inference gateway 边界。"""

from __future__ import annotations

from backend.service.application.models.detection_async_inference_gateway import (
    DETECTION_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX as CLASSIFICATION_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX,
    DETECTION_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX as CLASSIFICATION_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX,
    DetectionAsyncInferenceExecutor as ClassificationAsyncInferenceExecutor,
    DetectionAsyncInferenceGatewayDispatcher as ClassificationAsyncInferenceGatewayDispatcher,
    DetectionAsyncInferenceGatewayDispatcherRegistry as ClassificationAsyncInferenceGatewayDispatcherRegistry,
    QueueBackedDetectionAsyncInferenceClient as QueueBackedClassificationAsyncInferenceClient,
    build_detection_async_inference_gateway_queue_name as build_classification_async_inference_gateway_queue_name,
    deserialize_detection_async_inference_execution_result_payload as deserialize_classification_async_inference_execution_result_payload,
    normalize_detection_async_inference_deployment_id as normalize_classification_async_inference_deployment_id,
    normalize_detection_async_inference_owner_id as normalize_classification_async_inference_owner_id,
    serialize_detection_async_inference_execution_result as serialize_classification_async_inference_execution_result,
)

__all__ = [
    "CLASSIFICATION_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX",
    "CLASSIFICATION_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX",
    "ClassificationAsyncInferenceExecutor",
    "QueueBackedClassificationAsyncInferenceClient",
    "ClassificationAsyncInferenceGatewayDispatcher",
    "ClassificationAsyncInferenceGatewayDispatcherRegistry",
    "build_classification_async_inference_gateway_queue_name",
    "normalize_classification_async_inference_owner_id",
    "normalize_classification_async_inference_deployment_id",
    "serialize_classification_async_inference_execution_result",
    "deserialize_classification_async_inference_execution_result_payload",
]
