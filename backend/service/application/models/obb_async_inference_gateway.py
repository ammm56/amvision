"""obb async inference gateway 边界。"""

from __future__ import annotations

from backend.service.application.models.inference_gateway import (
    ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX as OBB_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX,
    ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX as OBB_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX,
    AsyncInferenceExecutor as ObbAsyncInferenceExecutor,
    AsyncInferenceGatewayDispatcher as ObbAsyncInferenceGatewayDispatcher,
    AsyncInferenceGatewayDispatcherRegistry as ObbAsyncInferenceGatewayDispatcherRegistry,
    QueueBackedAsyncInferenceClient as QueueBackedObbAsyncInferenceClient,
    build_async_inference_gateway_queue_name,
    deserialize_async_inference_execution_result_payload,
    normalize_async_inference_deployment_id,
    normalize_async_inference_owner_id,
    serialize_async_inference_execution_result,
)


def build_obb_async_inference_gateway_queue_name(
    *,
    owner_id: str,
    deployment_instance_id: str,
) -> str:
    """构建 obb async inference gateway 请求队列名。"""

    return build_async_inference_gateway_queue_name(
        owner_id=owner_id,
        deployment_instance_id=deployment_instance_id,
    )


def normalize_obb_async_inference_owner_id(value: object) -> str:
    """规范化 obb async inference owner id。"""

    return normalize_async_inference_owner_id(value)


def normalize_obb_async_inference_deployment_id(value: object) -> str:
    """规范化 obb async inference deployment id。"""

    return normalize_async_inference_deployment_id(value)


def serialize_obb_async_inference_execution_result(result: object) -> dict[str, object]:
    """序列化 obb async inference 执行结果。"""

    return serialize_async_inference_execution_result(
        task_type="obb",
        result=result,
    )


def deserialize_obb_async_inference_execution_result_payload(
    payload: object,
) -> dict[str, object]:
    """反序列化 obb async inference 执行结果。"""

    return deserialize_async_inference_execution_result_payload(
        task_type="obb",
        payload=payload,
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
