"""pose deployment process supervisor FastAPI 依赖。"""

from __future__ import annotations

from backend.service.application.models.pose_async_inference_gateway import (
    PoseAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)


async def get_pose_async_deployment_process_supervisor() -> DeploymentProcessSupervisor | None:
    from backend.service.api.app import get_app_state

    runtime = getattr(get_app_state(), "backend_service_runtime", None)
    if runtime is not None:
        return getattr(runtime, "pose_async_deployment_supervisor", None)
    return None


async def get_pose_sync_deployment_process_supervisor() -> DeploymentProcessSupervisor | None:
    from backend.service.api.app import get_app_state

    runtime = getattr(get_app_state(), "backend_service_runtime", None)
    if runtime is not None:
        return getattr(runtime, "pose_sync_deployment_supervisor", None)
    return None


async def get_pose_async_inference_gateway_dispatcher_registry() -> PoseAsyncInferenceGatewayDispatcherRegistry | None:
    from backend.service.api.app import get_app_state

    runtime = getattr(get_app_state(), "backend_service_runtime", None)
    if runtime is not None:
        return getattr(runtime, "pose_async_inference_gateway_registry", None)
    return None
