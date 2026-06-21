"""segmentation deployment process supervisor FastAPI 依赖。"""

from __future__ import annotations

from fastapi import Request

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.inference.segmentation_async_inference_gateway import (
    SegmentationAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)


def get_segmentation_async_deployment_process_supervisor(
    request: Request,
) -> DeploymentProcessSupervisor:
    """从 FastAPI 应用状态中读取异步 segmentation deployment 进程监督器。"""

    supervisor = getattr(request.app.state, "segmentation_async_deployment_process_supervisor", None)
    if not isinstance(supervisor, DeploymentProcessSupervisor):
        raise ServiceConfigurationError(
            "当前服务尚未完成异步 segmentation deployment 进程监督器装配",
            details={"state_field": "segmentation_async_deployment_process_supervisor"},
        )
    return supervisor


def get_segmentation_sync_deployment_process_supervisor(
    request: Request,
) -> DeploymentProcessSupervisor:
    """从 FastAPI 应用状态中读取同步 segmentation deployment 进程监督器。"""

    supervisor = getattr(request.app.state, "segmentation_sync_deployment_process_supervisor", None)
    if not isinstance(supervisor, DeploymentProcessSupervisor):
        raise ServiceConfigurationError(
            "当前服务尚未完成同步 segmentation deployment 进程监督器装配",
            details={"state_field": "segmentation_sync_deployment_process_supervisor"},
        )
    return supervisor


def get_segmentation_async_inference_gateway_dispatcher_registry(
    request: Request,
) -> SegmentationAsyncInferenceGatewayDispatcherRegistry:
    """从 FastAPI 应用状态中读取 segmentation async inference gateway dispatcher registry。"""

    registry = getattr(
        request.app.state,
        "segmentation_async_inference_gateway_dispatcher_registry",
        None,
    )
    if not isinstance(registry, SegmentationAsyncInferenceGatewayDispatcherRegistry):
        raise ServiceConfigurationError(
            "当前服务尚未完成 segmentation async inference gateway dispatcher registry 装配",
            details={"state_field": "segmentation_async_inference_gateway_dispatcher_registry"},
        )
    return registry
