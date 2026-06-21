"""detection async inference gateway 边界。"""

from __future__ import annotations

from types import SimpleNamespace

from backend.service.application.models.inference.inference_gateway import (
    ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX as DETECTION_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX,
    ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX as DETECTION_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX,
    AsyncInferenceExecutor as DetectionAsyncInferenceExecutor,
    AsyncInferenceGatewayDispatcher as DetectionAsyncInferenceGatewayDispatcher,
    AsyncInferenceGatewayDispatcherRegistry as DetectionAsyncInferenceGatewayDispatcherRegistry,
    QueueBackedAsyncInferenceClient as QueueBackedDetectionAsyncInferenceClient,
    build_async_inference_gateway_queue_name,
    deserialize_async_inference_execution_result_payload,
    normalize_async_inference_deployment_id,
    normalize_async_inference_owner_id,
    serialize_async_inference_execution_result,
)
from backend.service.application.runtime.contracts.detection import (
    DetectionPredictionExecutionResult,
)
from backend.service.application.runtime.serialization.detection import (
    deserialize_detection,
    deserialize_runtime_session_info,
)


def build_detection_async_inference_gateway_queue_name(
    *,
    owner_id: str,
    deployment_instance_id: str,
) -> str:
    """构建 detection async inference gateway 请求队列名。"""

    return build_async_inference_gateway_queue_name(
        owner_id=owner_id,
        deployment_instance_id=deployment_instance_id,
    )


def normalize_detection_async_inference_owner_id(value: object) -> str:
    """规范化 detection async inference owner id。"""

    return normalize_async_inference_owner_id(value)


def normalize_detection_async_inference_deployment_id(value: object) -> str:
    """规范化 detection async inference deployment id。"""

    return normalize_async_inference_deployment_id(value)


def serialize_detection_async_inference_execution_result(result: object) -> dict[str, object]:
    """序列化 detection async inference 执行结果。"""

    if getattr(result, "execution_result", None) is None and hasattr(result, "detections"):
        normalized_detections = []
        for item in getattr(result, "detections", ()):
            if isinstance(item, dict):
                parsed_item = deserialize_detection(item)
                if parsed_item is not None:
                    normalized_detections.append(parsed_item)
                continue
            normalized_detections.append(item)
        runtime_session_info = getattr(result, "runtime_session_info", None)
        normalized_result = SimpleNamespace(
            instance_id=getattr(result, "instance_id", None),
            execution_result=DetectionPredictionExecutionResult(
                detections=tuple(normalized_detections),
                latency_ms=getattr(result, "latency_ms", None),
                image_width=int(getattr(result, "image_width", 0) or 0),
                image_height=int(getattr(result, "image_height", 0) or 0),
                preview_image_bytes=(
                    getattr(result, "preview_image_bytes", None)
                    if isinstance(getattr(result, "preview_image_bytes", None), bytes)
                    else None
                ),
                runtime_session_info=(
                    deserialize_runtime_session_info(runtime_session_info)
                    if isinstance(runtime_session_info, dict)
                    else runtime_session_info
                ),
            ),
        )
        return serialize_async_inference_execution_result(
            task_type="detection",
            result=normalized_result,
        )
    return serialize_async_inference_execution_result(
        task_type="detection",
        result=result,
    )


def deserialize_detection_async_inference_execution_result_payload(
    payload: object,
) -> dict[str, object]:
    """反序列化 detection async inference 执行结果。"""

    return deserialize_async_inference_execution_result_payload(
        task_type="detection",
        payload=payload,
    )


__all__ = [
    "DETECTION_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX",
    "DETECTION_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX",
    "DetectionAsyncInferenceExecutor",
    "QueueBackedDetectionAsyncInferenceClient",
    "DetectionAsyncInferenceGatewayDispatcher",
    "DetectionAsyncInferenceGatewayDispatcherRegistry",
    "build_detection_async_inference_gateway_queue_name",
    "normalize_detection_async_inference_owner_id",
    "normalize_detection_async_inference_deployment_id",
    "serialize_detection_async_inference_execution_result",
    "deserialize_detection_async_inference_execution_result_payload",
]
