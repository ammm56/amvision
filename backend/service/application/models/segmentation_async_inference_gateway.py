"""segmentation async inference gateway 边界。"""

from __future__ import annotations

from backend.service.application.models.inference_gateway import (
    ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX as SEGMENTATION_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX,
    ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX as SEGMENTATION_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX,
    AsyncInferenceExecutor as SegmentationAsyncInferenceExecutor,
    AsyncInferenceGatewayDispatcher as SegmentationAsyncInferenceGatewayDispatcher,
    AsyncInferenceGatewayDispatcherRegistry as SegmentationAsyncInferenceGatewayDispatcherRegistry,
    QueueBackedAsyncInferenceClient as QueueBackedSegmentationAsyncInferenceClient,
    build_async_inference_gateway_queue_name,
    deserialize_async_inference_execution_result_payload,
    normalize_async_inference_deployment_id,
    normalize_async_inference_owner_id,
    serialize_async_inference_execution_result,
)


def build_segmentation_async_inference_gateway_queue_name(
    *,
    owner_id: str,
    deployment_instance_id: str,
) -> str:
    """构建 segmentation async inference gateway 请求队列名。"""

    return build_async_inference_gateway_queue_name(
        owner_id=owner_id,
        deployment_instance_id=deployment_instance_id,
    )


def normalize_segmentation_async_inference_owner_id(value: object) -> str:
    """规范化 segmentation async inference owner id。"""

    return normalize_async_inference_owner_id(value)


def normalize_segmentation_async_inference_deployment_id(value: object) -> str:
    """规范化 segmentation async inference deployment id。"""

    return normalize_async_inference_deployment_id(value)


def serialize_segmentation_async_inference_execution_result(result: object) -> dict[str, object]:
    """序列化 segmentation async inference 执行结果。"""

    return serialize_async_inference_execution_result(
        task_type="segmentation",
        result=result,
    )


def deserialize_segmentation_async_inference_execution_result_payload(
    payload: object,
) -> dict[str, object]:
    """反序列化 segmentation async inference 执行结果。"""

    return deserialize_async_inference_execution_result_payload(
        task_type="segmentation",
        payload=payload,
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
