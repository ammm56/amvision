"""detection deployment runtime 依赖注入。"""

from __future__ import annotations

from fastapi import Request

from backend.service.api.deps.yolox_deployment_process_supervisor import (
    get_yolox_async_deployment_process_supervisor as get_detection_async_deployment_process_supervisor,
)
from backend.service.api.deps.yolox_deployment_process_supervisor import (
    get_yolox_async_inference_gateway_dispatcher_registry,
    get_yolox_sync_deployment_process_supervisor as get_detection_sync_deployment_process_supervisor,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.detection_async_inference_gateway import (
    DetectionAsyncInferenceGatewayDispatcherRegistry,
)


def get_detection_async_inference_gateway_dispatcher_registry(
    request: Request,
) -> DetectionAsyncInferenceGatewayDispatcherRegistry:
    """返回 detection 公共 async inference gateway dispatcher registry。"""

    registry = get_yolox_async_inference_gateway_dispatcher_registry(request)
    if not isinstance(registry, DetectionAsyncInferenceGatewayDispatcherRegistry):
        raise ServiceConfigurationError(
            "应用状态中的 detection async inference gateway dispatcher registry 类型不合法",
            details={"state_field": "yolox_async_inference_gateway_dispatcher_registry"},
        )
    return registry

