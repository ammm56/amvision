"""obb deployment process supervisor FastAPI 依赖。"""

from __future__ import annotations

from backend.service.application.models.obb_async_inference_gateway import (
    ObbAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessSupervisor,
)


async def get_obb_async_deployment_process_supervisor() -> YoloXDeploymentProcessSupervisor | None:
    from backend.service.api.app import get_app_state

    runtime = getattr(get_app_state(), "backend_service_runtime", None)
    if runtime is not None:
        return getattr(runtime, "obb_async_deployment_supervisor", None)
    return None


async def get_obb_sync_deployment_process_supervisor() -> YoloXDeploymentProcessSupervisor | None:
    from backend.service.api.app import get_app_state

    runtime = getattr(get_app_state(), "backend_service_runtime", None)
    if runtime is not None:
        return getattr(runtime, "obb_sync_deployment_supervisor", None)
    return None


async def get_obb_async_inference_gateway_dispatcher_registry() -> ObbAsyncInferenceGatewayDispatcherRegistry | None:
    from backend.service.api.app import get_app_state

    runtime = getattr(get_app_state(), "backend_service_runtime", None)
    if runtime is not None:
        return getattr(runtime, "obb_async_inference_gateway_registry", None)
    return None
