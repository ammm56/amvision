"""classification deployment process supervisor FastAPI 依赖。"""

from __future__ import annotations

from backend.service.application.models.classification_async_inference_gateway import (
    ClassificationAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessSupervisor,
)


async def get_classification_async_deployment_process_supervisor() -> YoloXDeploymentProcessSupervisor | None:
    from backend.service.api.app import get_app_state

    runtime = getattr(get_app_state(), "backend_service_runtime", None)
    if runtime is not None:
        return getattr(runtime, "classification_async_deployment_supervisor", None)
    return None


async def get_classification_sync_deployment_process_supervisor() -> YoloXDeploymentProcessSupervisor | None:
    from backend.service.api.app import get_app_state

    runtime = getattr(get_app_state(), "backend_service_runtime", None)
    if runtime is not None:
        return getattr(runtime, "classification_sync_deployment_supervisor", None)
    return None


async def get_classification_async_inference_gateway_dispatcher_registry() -> ClassificationAsyncInferenceGatewayDispatcherRegistry | None:
    from backend.service.api.app import get_app_state

    runtime = getattr(get_app_state(), "backend_service_runtime", None)
    if runtime is not None:
        return getattr(runtime, "classification_async_inference_gateway_registry", None)
    return None
