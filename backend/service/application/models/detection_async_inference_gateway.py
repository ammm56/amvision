"""detection 公共 async inference gateway 边界。"""

from __future__ import annotations

from backend.service.application.models.yolox_async_inference_gateway import (
    YOLOX_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX as DETECTION_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX,
)
from backend.service.application.models.yolox_async_inference_gateway import (
    YOLOX_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX as DETECTION_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX,
)
from backend.service.application.models.yolox_async_inference_gateway import (
    QueueBackedYoloXAsyncInferenceClient as QueueBackedDetectionAsyncInferenceClient,
)
from backend.service.application.models.yolox_async_inference_gateway import (
    YoloXAsyncInferenceExecutor as DetectionAsyncInferenceExecutor,
)
from backend.service.application.models.yolox_async_inference_gateway import (
    YoloXAsyncInferenceGatewayDispatcher as DetectionAsyncInferenceGatewayDispatcher,
)
from backend.service.application.models.yolox_async_inference_gateway import (
    YoloXAsyncInferenceGatewayDispatcherRegistry as DetectionAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.models.yolox_async_inference_gateway import (
    build_yolox_async_inference_gateway_queue_name as build_detection_async_inference_gateway_queue_name,
)
from backend.service.application.models.yolox_async_inference_gateway import (
    deserialize_yolox_async_inference_execution_result_payload as deserialize_detection_async_inference_execution_result_payload,
)
from backend.service.application.models.yolox_async_inference_gateway import (
    normalize_yolox_async_inference_deployment_id as normalize_detection_async_inference_deployment_id,
)
from backend.service.application.models.yolox_async_inference_gateway import (
    normalize_yolox_async_inference_owner_id as normalize_detection_async_inference_owner_id,
)
from backend.service.application.models.yolox_async_inference_gateway import (
    serialize_yolox_async_inference_execution_result as serialize_detection_async_inference_execution_result,
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

