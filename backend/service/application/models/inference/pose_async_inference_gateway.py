"""pose async inference gateway 边界。"""

from __future__ import annotations

from backend.service.application.models.inference.inference_gateway import (
    ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX as POSE_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX,
    ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX as POSE_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX,
    AsyncInferenceExecutor as PoseAsyncInferenceExecutor,
    AsyncInferenceGatewayDispatcher as PoseAsyncInferenceGatewayDispatcher,
    AsyncInferenceGatewayDispatcherRegistry as PoseAsyncInferenceGatewayDispatcherRegistry,
    QueueBackedAsyncInferenceClient as QueueBackedPoseAsyncInferenceClient,
    build_async_inference_gateway_queue_name,
    deserialize_async_inference_execution_result_payload,
    normalize_async_inference_deployment_id,
    normalize_async_inference_owner_id,
    serialize_async_inference_execution_result,
)


def build_pose_async_inference_gateway_queue_name(
    *,
    owner_id: str,
    deployment_instance_id: str,
) -> str:
    """构建 pose async inference gateway 请求队列名。"""

    return build_async_inference_gateway_queue_name(
        owner_id=owner_id,
        deployment_instance_id=deployment_instance_id,
    )


def normalize_pose_async_inference_owner_id(value: object) -> str:
    """规范化 pose async inference owner id。"""

    return normalize_async_inference_owner_id(value)


def normalize_pose_async_inference_deployment_id(value: object) -> str:
    """规范化 pose async inference deployment id。"""

    return normalize_async_inference_deployment_id(value)


def serialize_pose_async_inference_execution_result(result: object) -> dict[str, object]:
    """序列化 pose async inference 执行结果。"""

    return serialize_async_inference_execution_result(
        task_type="pose",
        result=result,
    )


def deserialize_pose_async_inference_execution_result_payload(
    payload: object,
) -> dict[str, object]:
    """反序列化 pose async inference 执行结果。"""

    return deserialize_async_inference_execution_result_payload(
        task_type="pose",
        payload=payload,
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
