"""detection deployment 路由响应模型与辅助函数。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.yolox_deployments import (
    YoloXDeploymentInstanceResponse,
    YoloXDeploymentInstanceView,
    YoloXDeploymentProcessEventResponse,
    YoloXDeploymentProcessStatusResponse,
    YoloXDeploymentRuntimeHealthResponse,
    _build_deployment_instance_response,
    _build_deployment_process_event_response,
    _ensure_deployment_visible,
    _run_process_health_action,
    _run_process_status_action,
)


class DetectionDeploymentInstanceResponse(YoloXDeploymentInstanceResponse):
    """描述 detection DeploymentInstance 摘要与详情响应。"""


class DetectionDeploymentProcessStatusResponse(YoloXDeploymentProcessStatusResponse):
    """描述 detection deployment 子进程监督状态。"""


class DetectionDeploymentRuntimeHealthResponse(YoloXDeploymentRuntimeHealthResponse):
    """描述 detection deployment 子进程与实例池的详细健康视图。"""


class DetectionDeploymentProcessEventResponse(YoloXDeploymentProcessEventResponse):
    """描述 detection deployment 生命周期与健康事件响应。"""


def _ensure_detection_deployment_visible(*, principal, view: YoloXDeploymentInstanceView) -> None:
    """校验当前主体是否可以访问指定 detection DeploymentInstance。"""

    _ensure_deployment_visible(principal=principal, view=view)


def _build_detection_deployment_instance_response(
    view: YoloXDeploymentInstanceView,
) -> DetectionDeploymentInstanceResponse:
    """把 DeploymentInstance 视图转换为 detection REST 响应。"""

    response = _build_deployment_instance_response(view)
    return DetectionDeploymentInstanceResponse.model_validate(response.model_dump())


def _run_detection_process_status_action(**kwargs) -> DetectionDeploymentProcessStatusResponse:
    """执行指定通道的 detection deployment 进程状态动作。"""

    response = _run_process_status_action(**kwargs)
    return DetectionDeploymentProcessStatusResponse.model_validate(response.model_dump())


def _run_detection_process_health_action(**kwargs) -> DetectionDeploymentRuntimeHealthResponse:
    """执行指定通道的 detection deployment 进程健康动作。"""

    response = _run_process_health_action(**kwargs)
    return DetectionDeploymentRuntimeHealthResponse.model_validate(response.model_dump())


def _build_detection_deployment_process_event_response(
    item,
) -> DetectionDeploymentProcessEventResponse:
    """把 deployment 事件转换为 detection REST 响应。"""

    response = _build_deployment_process_event_response(item)
    return DetectionDeploymentProcessEventResponse.model_validate(response.model_dump())

