"""deployment 运行控制与推理路由公共辅助函数。"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.model_type_support import (
    ensure_requested_platform_model_type_matches,
)
from backend.service.application.runtime.deployment_process_supervisor import (
    DeploymentProcessHealth,
    DeploymentProcessInstanceHealth,
    DeploymentProcessKeepWarmStatus,
    DeploymentProcessStatus,
    DeploymentProcessSupervisor,
)


class DeploymentRuntimeInstanceHealthResponse(BaseModel):
    """描述单个 deployment 推理实例的健康状态。"""

    instance_id: str = Field(description="推理实例 id")
    healthy: bool = Field(description="是否健康")
    warmed: bool = Field(description="是否已完成模型加载")
    busy: bool = Field(description="当前是否正在处理请求")
    last_error: str | None = Field(default=None, description="最近一次失败错误")


class DeploymentProcessKeepWarmResponse(BaseModel):
    """描述 deployment 子进程内 keep-warm 的当前状态。"""

    enabled: bool = Field(default=False, description="当前 deployment 是否启用 keep-warm")
    activated: bool = Field(default=False, description="keep-warm 是否已经被 warmup 或真实推理激活")
    paused: bool = Field(default=False, description="当前是否因为控制面动作或真实请求而暂停")
    idle: bool = Field(default=True, description="当前是否没有 keep-warm dummy infer 正在执行")
    interval_seconds: float = Field(default=0.0, description="keep-warm 连续 dummy infer 的最小间隔秒数")
    yield_timeout_seconds: float = Field(default=0.0, description="真实请求等待 keep-warm 让出的最长秒数")
    success_count: int = Field(default=0, description="keep-warm 成功次数当前安全整数窗口值")
    success_count_rollover_count: int = Field(default=0, description="success_count rollover 次数")
    error_count: int = Field(default=0, description="keep-warm 失败次数当前安全整数窗口值")
    error_count_rollover_count: int = Field(default=0, description="error_count rollover 次数")
    last_error: str | None = Field(default=None, description="最近一次 keep-warm 失败错误")


class DeploymentProcessStatusResponse(BaseModel):
    """描述 deployment 子进程监督状态。"""

    deployment_instance_id: str = Field(description="DeploymentInstance id")
    display_name: str = Field(description="展示名称")
    runtime_mode: str = Field(description="运行时通道；sync 或 async")
    desired_state: str = Field(description="监督器期望状态；running 或 stopped")
    process_state: str = Field(description="当前进程状态；running、stopped 或 crashed")
    process_id: int | None = Field(default=None, description="当前子进程 pid")
    auto_restart: bool = Field(description="是否启用崩溃自动拉起")
    restart_count: int = Field(description="已经发生的自动拉起次数当前安全整数窗口值")
    restart_count_rollover_count: int = Field(default=0, description="restart_count rollover 次数")
    last_exit_code: int | None = Field(default=None, description="最近一次退出码")
    last_error: str | None = Field(default=None, description="最近一次监督错误")
    instance_count: int = Field(description="实例数量")


class DeploymentRuntimeHealthResponse(DeploymentProcessStatusResponse):
    """描述 deployment 子进程与实例池的详细健康视图。"""

    healthy_instance_count: int = Field(description="健康实例数量")
    warmed_instance_count: int = Field(description="已预热实例数量")
    pinned_output_total_bytes: int = Field(default=0, description="当前所有已加载 session 的 pinned output host buffer 总字节数")
    instances: list[DeploymentRuntimeInstanceHealthResponse] = Field(default_factory=list, description="实例级健康状态列表")
    keep_warm: DeploymentProcessKeepWarmResponse = Field(default_factory=DeploymentProcessKeepWarmResponse, description="keep-warm 运行状态")
    local_buffer_broker: dict[str, object] = Field(default_factory=dict, description="LocalBufferBroker 接入状态、输入计数和最近错误")


def ensure_deployment_visible(
    *,
    principal: AuthenticatedPrincipal,
    project_id: str,
    deployment_instance_id: str,
) -> None:
    """校验当前主体是否可以访问指定 DeploymentInstance。"""

    if principal.project_ids and project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的 DeploymentInstance",
            details={"deployment_instance_id": deployment_instance_id},
        )


def ensure_requested_model_type_matches(
    *,
    requested_model_type: str | None,
    resolved_model_type: str,
    deployment_instance_id: str,
) -> None:
    """校验请求中的模型分类与 DeploymentInstance 绑定模型一致。"""

    ensure_requested_platform_model_type_matches(
        requested_model_type=requested_model_type,
        resolved_model_type=resolved_model_type,
        deployment_instance_id=deployment_instance_id,
    )


def require_running_deployment_process(
    *,
    deployment_process_supervisor: DeploymentProcessSupervisor,
    process_config: object,
    runtime_mode: str,
) -> None:
    """校验目标 deployment 子进程已经处于 running 状态。"""

    status = deployment_process_supervisor.get_status(process_config)
    if status.process_state == "running":
        return
    raise InvalidRequestError(
        "当前 deployment 进程尚未启动，请先调用 start 或 warmup 接口",
        details={
            "deployment_instance_id": getattr(process_config, "deployment_instance_id", None),
            "runtime_mode": runtime_mode,
            "process_state": status.process_state,
            "required_actions": [f"{runtime_mode}/start", f"{runtime_mode}/warmup"],
        },
    )


def read_async_inference_service_id(
    request: Request,
    *,
    task_type: str,
) -> str | None:
    """读取当前 async inference service 稳定 id。"""

    task_specific_value = getattr(request.app.state, f"{task_type}_async_inference_service_id", None)
    if isinstance(task_specific_value, str) and task_specific_value.strip():
        return task_specific_value.strip()
    generic_value = getattr(request.app.state, "async_inference_service_id", None)
    if isinstance(generic_value, str) and generic_value.strip():
        return generic_value.strip()
    return None


def run_deployment_process_status_action(
    *,
    deployment_instance_id: str,
    principal: AuthenticatedPrincipal,
    deployment_service: Any,
    supervisor: DeploymentProcessSupervisor,
    gateway_dispatcher_registry: Any | None = None,
    runtime_mode: str,
    action: str,
) -> DeploymentProcessStatusResponse:
    """执行指定通道的 deployment 进程状态动作。"""

    view = deployment_service.get_deployment_instance(deployment_instance_id)
    ensure_deployment_visible(
        principal=principal,
        project_id=getattr(view, "project_id"),
        deployment_instance_id=deployment_instance_id,
    )
    process_config = deployment_service.resolve_process_config(deployment_instance_id)
    if action == "start":
        process_status = supervisor.start_deployment(process_config)
        if runtime_mode == "async":
            _ensure_async_dispatcher(gateway_dispatcher_registry, deployment_instance_id)
    elif action == "stop":
        process_status = supervisor.stop_deployment(process_config)
        if runtime_mode == "async":
            _stop_async_dispatcher(gateway_dispatcher_registry, deployment_instance_id)
    elif action == "status":
        process_status = supervisor.get_status(process_config)
    else:
        raise InvalidRequestError(
            "未知的 deployment 状态动作",
            details={"action": action},
        )
    return build_deployment_process_status_response(view=view, process_status=process_status, runtime_mode=runtime_mode)


def run_deployment_process_health_action(
    *,
    deployment_instance_id: str,
    principal: AuthenticatedPrincipal,
    deployment_service: Any,
    supervisor: DeploymentProcessSupervisor,
    gateway_dispatcher_registry: Any | None = None,
    runtime_mode: str,
    action: str,
) -> DeploymentRuntimeHealthResponse:
    """执行指定通道的 deployment 进程健康动作。"""

    view = deployment_service.get_deployment_instance(deployment_instance_id)
    ensure_deployment_visible(
        principal=principal,
        project_id=getattr(view, "project_id"),
        deployment_instance_id=deployment_instance_id,
    )
    process_config = deployment_service.resolve_process_config(deployment_instance_id)
    if action == "warmup":
        process_health = supervisor.warmup_deployment(process_config)
        if runtime_mode == "async":
            _ensure_async_dispatcher(gateway_dispatcher_registry, deployment_instance_id)
    elif action == "reset":
        process_health = supervisor.reset_deployment(process_config)
    elif action == "health":
        process_health = supervisor.get_health(process_config)
    else:
        raise InvalidRequestError(
            "未知的 deployment 健康动作",
            details={"action": action},
        )
    return build_deployment_runtime_health_response(view=view, process_health=process_health, runtime_mode=runtime_mode)


def build_deployment_process_status_response(
    *,
    view: object,
    process_status: DeploymentProcessStatus,
    runtime_mode: str,
) -> DeploymentProcessStatusResponse:
    """把 deployment 视图与进程状态组合为状态响应。"""

    return DeploymentProcessStatusResponse(
        deployment_instance_id=getattr(view, "deployment_instance_id"),
        display_name=getattr(view, "display_name"),
        runtime_mode=runtime_mode,
        desired_state=process_status.desired_state,
        process_state=process_status.process_state,
        process_id=process_status.process_id,
        auto_restart=process_status.auto_restart,
        restart_count=process_status.restart_count,
        restart_count_rollover_count=process_status.restart_count_rollover_count,
        last_exit_code=process_status.last_exit_code,
        last_error=process_status.last_error,
        instance_count=process_status.instance_count,
    )


def build_deployment_runtime_health_response(
    *,
    view: object,
    process_health: DeploymentProcessHealth,
    runtime_mode: str,
) -> DeploymentRuntimeHealthResponse:
    """把 deployment 视图与进程健康状态组合为详细响应。"""

    return DeploymentRuntimeHealthResponse(
        deployment_instance_id=getattr(view, "deployment_instance_id"),
        display_name=getattr(view, "display_name"),
        runtime_mode=runtime_mode,
        desired_state=process_health.desired_state,
        process_state=process_health.process_state,
        process_id=process_health.process_id,
        auto_restart=process_health.auto_restart,
        restart_count=process_health.restart_count,
        restart_count_rollover_count=process_health.restart_count_rollover_count,
        last_exit_code=process_health.last_exit_code,
        last_error=process_health.last_error,
        instance_count=process_health.instance_count,
        healthy_instance_count=process_health.healthy_instance_count,
        warmed_instance_count=process_health.warmed_instance_count,
        pinned_output_total_bytes=process_health.pinned_output_total_bytes,
        instances=[_build_runtime_instance_health_response(item) for item in process_health.instances],
        keep_warm=_build_keep_warm_response(process_health.keep_warm),
        local_buffer_broker=dict(process_health.local_buffer_broker),
    )


def _build_runtime_instance_health_response(
    item: DeploymentProcessInstanceHealth,
) -> DeploymentRuntimeInstanceHealthResponse:
    """把 runtime 实例健康状态转换为 REST 响应。"""

    return DeploymentRuntimeInstanceHealthResponse(
        instance_id=item.instance_id,
        healthy=item.healthy,
        warmed=item.warmed,
        busy=item.busy,
        last_error=item.last_error,
    )


def _build_keep_warm_response(
    item: DeploymentProcessKeepWarmStatus | None,
) -> DeploymentProcessKeepWarmResponse:
    """把 keep-warm 状态转换为 REST 响应。"""

    if item is None:
        return DeploymentProcessKeepWarmResponse()
    return DeploymentProcessKeepWarmResponse(
        enabled=item.enabled,
        activated=item.activated,
        paused=item.paused,
        idle=item.idle,
        interval_seconds=item.interval_seconds,
        yield_timeout_seconds=item.yield_timeout_seconds,
        success_count=item.success_count,
        success_count_rollover_count=item.success_count_rollover_count,
        error_count=item.error_count,
        error_count_rollover_count=item.error_count_rollover_count,
        last_error=item.last_error,
    )


def _ensure_async_dispatcher(
    gateway_dispatcher_registry: Any | None,
    deployment_instance_id: str,
) -> None:
    """在 async deployment 启动或 warmup 后确保 dispatcher 已经就绪。"""

    if gateway_dispatcher_registry is None:
        return
    ensure_dispatcher = getattr(gateway_dispatcher_registry, "ensure_dispatcher_for_deployment", None)
    if callable(ensure_dispatcher):
        ensure_dispatcher(deployment_instance_id)


def _stop_async_dispatcher(
    gateway_dispatcher_registry: Any | None,
    deployment_instance_id: str,
) -> None:
    """在 async deployment 停止后关闭 dispatcher。"""

    if gateway_dispatcher_registry is None:
        return
    stop_dispatcher = getattr(gateway_dispatcher_registry, "stop_dispatcher_for_deployment", None)
    if callable(stop_dispatcher):
        stop_dispatcher(deployment_instance_id)
