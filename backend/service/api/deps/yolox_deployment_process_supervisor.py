"""YOLOX deployment 进程监督器依赖定义。"""

from __future__ import annotations

from fastapi import Request

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessSupervisor,
)


def get_yolox_sync_deployment_process_supervisor(request: Request) -> YoloXDeploymentProcessSupervisor:
    """从 FastAPI 应用状态中读取同步 deployment 进程监督器。

    参数：
    - request：当前 HTTP 请求。

    返回：
    - 当前应用使用的同步 deployment 进程监督器。
    """

    supervisor = getattr(request.app.state, "yolox_sync_deployment_process_supervisor", None)
    if not isinstance(supervisor, YoloXDeploymentProcessSupervisor):
        raise ServiceConfigurationError(
            "当前服务尚未完成同步 deployment 进程监督器装配",
            details={"state_field": "yolox_sync_deployment_process_supervisor"},
        )
    return supervisor


def get_yolox_async_deployment_process_supervisor(request: Request) -> YoloXDeploymentProcessSupervisor:
    """从 FastAPI 应用状态中读取异步 deployment 进程监督器。

    参数：
    - request：当前 HTTP 请求。

    返回：
    - 当前应用使用的异步 deployment 进程监督器。
    """

    supervisor = getattr(request.app.state, "yolox_async_deployment_process_supervisor", None)
    if not isinstance(supervisor, YoloXDeploymentProcessSupervisor):
        raise ServiceConfigurationError(
            "当前服务尚未完成异步 deployment 进程监督器装配",
            details={"state_field": "yolox_async_deployment_process_supervisor"},
        )
    return supervisor