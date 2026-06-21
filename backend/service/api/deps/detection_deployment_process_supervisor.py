"""detection deployment runtime 依赖注入。"""

from __future__ import annotations

from fastapi import Request

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.inference.detection_async_inference_gateway import (
    DetectionAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)


def get_detection_sync_deployment_process_supervisor(
    request: Request,
) -> DeploymentProcessSupervisor:
    """从 FastAPI 应用状态中读取同步 detection deployment 进程监督器。"""

    supervisor = getattr(request.app.state, "detection_sync_deployment_process_supervisor", None)
    if not isinstance(supervisor, DeploymentProcessSupervisor):
        raise ServiceConfigurationError(
            "当前服务尚未完成同步 detection deployment 进程监督器装配",
            details={"state_field": "detection_sync_deployment_process_supervisor"},
        )
    return supervisor


def get_detection_async_deployment_process_supervisor(
    request: Request,
) -> DeploymentProcessSupervisor:
    """从 FastAPI 应用状态中读取异步 detection deployment 进程监督器。"""

    supervisor = getattr(request.app.state, "detection_async_deployment_process_supervisor", None)
    if not isinstance(supervisor, DeploymentProcessSupervisor):
        raise ServiceConfigurationError(
            "当前服务尚未完成异步 detection deployment 进程监督器装配",
            details={"state_field": "detection_async_deployment_process_supervisor"},
        )
    return supervisor


def get_detection_async_inference_gateway_dispatcher_registry(
    request: Request,
) -> DetectionAsyncInferenceGatewayDispatcherRegistry:
    """从 FastAPI 应用状态中读取 detection async inference gateway dispatcher registry。"""

    registry = getattr(
        request.app.state,
        "detection_async_inference_gateway_dispatcher_registry",
        None,
    )
    if not isinstance(registry, DetectionAsyncInferenceGatewayDispatcherRegistry):
        raise ServiceConfigurationError(
            "当前服务尚未完成 detection async inference gateway dispatcher registry 装配",
            details={"state_field": "detection_async_inference_gateway_dispatcher_registry"},
        )
    return registry
