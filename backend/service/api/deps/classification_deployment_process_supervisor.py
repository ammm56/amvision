"""classification deployment process supervisor FastAPI 依赖。"""

from __future__ import annotations

from fastapi import Request

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.inference.classification_async_inference_gateway import (
    ClassificationAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)


def get_classification_async_deployment_process_supervisor(
    request: Request,
) -> DeploymentProcessSupervisor:
    """从 FastAPI 应用状态中读取异步 classification deployment 进程监督器。"""

    supervisor = getattr(request.app.state, "classification_async_deployment_process_supervisor", None)
    if not isinstance(supervisor, DeploymentProcessSupervisor):
        raise ServiceConfigurationError(
            "当前服务尚未完成异步 classification deployment 进程监督器装配",
            details={"state_field": "classification_async_deployment_process_supervisor"},
        )
    return supervisor


def get_classification_sync_deployment_process_supervisor(
    request: Request,
) -> DeploymentProcessSupervisor:
    """从 FastAPI 应用状态中读取同步 classification deployment 进程监督器。"""

    supervisor = getattr(request.app.state, "classification_sync_deployment_process_supervisor", None)
    if not isinstance(supervisor, DeploymentProcessSupervisor):
        raise ServiceConfigurationError(
            "当前服务尚未完成同步 classification deployment 进程监督器装配",
            details={"state_field": "classification_sync_deployment_process_supervisor"},
        )
    return supervisor


def get_classification_async_inference_gateway_dispatcher_registry(
    request: Request,
) -> ClassificationAsyncInferenceGatewayDispatcherRegistry:
    """从 FastAPI 应用状态中读取 classification async inference gateway dispatcher registry。"""

    registry = getattr(
        request.app.state,
        "classification_async_inference_gateway_dispatcher_registry",
        None,
    )
    if not isinstance(registry, ClassificationAsyncInferenceGatewayDispatcherRegistry):
        raise ServiceConfigurationError(
            "当前服务尚未完成 classification async inference gateway dispatcher registry 装配",
            details={"state_field": "classification_async_inference_gateway_dispatcher_registry"},
        )
    return registry
