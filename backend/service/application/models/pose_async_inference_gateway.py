"""pose 公共 async inference gateway 边界。"""

from __future__ import annotations

from backend.service.application.models.detection_async_inference_gateway import (
    DETECTION_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX as POSE_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX,
    DETECTION_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX as POSE_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX,
    DetectionAsyncInferenceExecutor as PoseAsyncInferenceExecutor,
    DetectionAsyncInferenceGatewayDispatcher as PoseAsyncInferenceGatewayDispatcher,
    DetectionAsyncInferenceGatewayDispatcherRegistry as PoseAsyncInferenceGatewayDispatcherRegistry,
    QueueBackedDetectionAsyncInferenceClient as QueueBackedPoseAsyncInferenceClient,
    build_detection_async_inference_gateway_queue_name as build_pose_async_inference_gateway_queue_name,
    deserialize_detection_async_inference_execution_result_payload as deserialize_pose_async_inference_execution_result_payload,
    normalize_detection_async_inference_deployment_id as normalize_pose_async_inference_deployment_id,
    normalize_detection_async_inference_owner_id as normalize_pose_async_inference_owner_id,
    serialize_detection_async_inference_execution_result as serialize_pose_async_inference_execution_result,
)

__all__ = [
    "POSE_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX",
    "POSE_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX",
    "PoseAsyncInferenceExecutor",
    "QueueBackedPoseAsyncInferenceClient",
    "PoseAsyncInferenceGatewayDispatcher",
    "PoseAsyncInferenceGatewayDispatcherRegistry",
    "build_pose_async_inference_gateway_queue_name",
    "normalize_pose_async_inference_owner_id",
    "normalize_pose_async_inference_deployment_id",
    "serialize_pose_async_inference_execution_result",
    "deserialize_pose_async_inference_execution_result_payload",
]
