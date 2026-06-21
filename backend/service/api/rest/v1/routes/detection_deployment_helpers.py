"""detection deployment 路由响应模型与辅助函数。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.deployments.detection_deployment_service import (
    DetectionDeploymentInstanceView,
    SqlAlchemyDetectionDeploymentService,
)
from backend.service.application.errors import ResourceNotFoundError
from backend.service.application.models.inference.detection_async_inference_gateway import (
    DetectionAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment.deployment_events import DetectionDeploymentProcessEvent
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessHealth,
    DeploymentProcessInstanceHealth,
    DeploymentProcessKeepWarmStatus,
    DeploymentProcessStatus,
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class DetectionDeploymentInstanceResponse(BaseModel):
    """描述 detection DeploymentInstance 摘要与详情响应。"""

    deployment_instance_id: str = Field(description="DeploymentInstance id")
    project_id: str = Field(description="所属 Project id")
    display_name: str = Field(description="展示名称")
    status: str = Field(description="部署实例状态")
    model_id: str = Field(description="关联 Model id")
    model_version_id: str = Field(description="绑定的 ModelVersion id")
    model_build_id: str | None = Field(default=None, description="绑定的 ModelBuild id")
    model_name: str = Field(description="模型名")
    model_scale: str = Field(description="模型 scale")
    task_type: str = Field(description="任务类型")
    source_kind: str = Field(description="ModelVersion 来源类型")
    runtime_profile_id: str | None = Field(default=None, description="RuntimeProfile id")
    runtime_backend: str = Field(description="运行时 backend")
    device_name: str = Field(description="默认 device 名称")
    runtime_precision: str = Field(description="运行时 precision")
    runtime_execution_mode: str = Field(description="公开展示的 backend:precision:device 运行模式")
    instance_count: int = Field(description="实例化数量")
    input_size: tuple[int, int] = Field(description="默认输入尺寸")
    labels: tuple[str, ...] = Field(description="类别列表")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="最后更新时间")
    created_by: str | None = Field(default=None, description="创建主体 id")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class DetectionDeploymentRuntimeInstanceHealthResponse(BaseModel):
    """描述单个 deployment 推理实例的健康状态。"""

    instance_id: str = Field(description="推理实例 id")
    healthy: bool = Field(description="是否健康")
    warmed: bool = Field(description="是否已完成模型加载")
    busy: bool = Field(description="当前是否正在处理请求")
    last_error: str | None = Field(default=None, description="最近一次失败错误")


class DetectionDeploymentProcessKeepWarmResponse(BaseModel):
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


class DetectionDeploymentProcessStatusResponse(BaseModel):
    """描述 detection deployment 子进程监督状态。"""

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


class DetectionDeploymentRuntimeHealthResponse(DetectionDeploymentProcessStatusResponse):
    """描述 detection deployment 子进程与实例池的详细健康视图。"""

    healthy_instance_count: int = Field(description="健康实例数量")
    warmed_instance_count: int = Field(description="已预热实例数量")
    pinned_output_total_bytes: int = Field(default=0, description="当前所有已加载 session 的 pinned output host buffer 总字节数")
    instances: list[DetectionDeploymentRuntimeInstanceHealthResponse] = Field(default_factory=list, description="实例级健康状态列表")
    keep_warm: DetectionDeploymentProcessKeepWarmResponse = Field(default_factory=DetectionDeploymentProcessKeepWarmResponse, description="keep-warm 运行状态")
    local_buffer_broker: dict[str, object] = Field(default_factory=dict, description="LocalBufferBroker 接入状态、输入计数和最近错误")


class DetectionDeploymentProcessEventResponse(BaseModel):
    """描述 detection deployment 生命周期与健康事件响应。"""

    deployment_instance_id: str = Field(description="DeploymentInstance id")
    runtime_mode: str = Field(description="运行时通道；sync 或 async")
    sequence: int = Field(description="事件顺序号")
    event_type: str = Field(description="事件类型")
    created_at: str = Field(description="事件发生时间")
    message: str = Field(description="事件摘要消息")
    payload: dict[str, object] = Field(default_factory=dict, description="结构化事件正文")


def _ensure_detection_deployment_visible(
    *,
    principal: AuthenticatedPrincipal,
    view: DetectionDeploymentInstanceView,
) -> None:
    """校验当前主体是否可以访问指定 detection DeploymentInstance。"""

    if principal.project_ids and view.project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的 DeploymentInstance",
            details={"deployment_instance_id": view.deployment_instance_id},
        )


def _build_detection_deployment_instance_response(
    view: DetectionDeploymentInstanceView,
) -> DetectionDeploymentInstanceResponse:
    """把 DeploymentInstance 视图转换为 detection REST 响应。"""

    return DetectionDeploymentInstanceResponse(
        deployment_instance_id=view.deployment_instance_id,
        project_id=view.project_id,
        display_name=view.display_name,
        status=view.status,
        model_id=view.model_id,
        model_version_id=view.model_version_id,
        model_build_id=view.model_build_id,
        model_name=view.model_name,
        model_scale=view.model_scale,
        task_type=view.task_type,
        source_kind=view.source_kind,
        runtime_profile_id=view.runtime_profile_id,
        runtime_backend=view.runtime_backend,
        device_name=view.device_name,
        runtime_precision=view.runtime_precision,
        runtime_execution_mode=view.runtime_execution_mode,
        instance_count=view.instance_count,
        input_size=view.input_size,
        labels=view.labels,
        created_at=view.created_at,
        updated_at=view.updated_at,
        created_by=view.created_by,
        metadata=dict(view.metadata),
    )


def _run_detection_process_status_action(
    *,
    deployment_instance_id: str,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    supervisor: DeploymentProcessSupervisor,
    gateway_dispatcher_registry: DetectionAsyncInferenceGatewayDispatcherRegistry | None = None,
    runtime_mode: str,
    action: str,
) -> DetectionDeploymentProcessStatusResponse:
    """执行指定通道的 detection deployment 进程状态动作。"""

    service = SqlAlchemyDetectionDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    view = service.get_deployment_instance(deployment_instance_id)
    _ensure_detection_deployment_visible(principal=principal, view=view)
    process_config = service.resolve_process_config(deployment_instance_id)
    if action == "start":
        process_status = supervisor.start_deployment(process_config)
        if runtime_mode == "async" and gateway_dispatcher_registry is not None:
            gateway_dispatcher_registry.ensure_dispatcher_for_deployment(deployment_instance_id)
    elif action == "stop":
        process_status = supervisor.stop_deployment(process_config)
        if runtime_mode == "async" and gateway_dispatcher_registry is not None:
            gateway_dispatcher_registry.stop_dispatcher_for_deployment(deployment_instance_id)
    else:
        process_status = supervisor.get_status(process_config)
    return _build_detection_process_status_response(view, process_status, runtime_mode)


def _run_detection_process_health_action(
    *,
    deployment_instance_id: str,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    supervisor: DeploymentProcessSupervisor,
    gateway_dispatcher_registry: DetectionAsyncInferenceGatewayDispatcherRegistry | None = None,
    runtime_mode: str,
    action: str,
) -> DetectionDeploymentRuntimeHealthResponse:
    """执行指定通道的 detection deployment 进程健康动作。"""

    service = SqlAlchemyDetectionDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    view = service.get_deployment_instance(deployment_instance_id)
    _ensure_detection_deployment_visible(principal=principal, view=view)
    process_config = service.resolve_process_config(deployment_instance_id)
    if action == "warmup":
        process_health = supervisor.warmup_deployment(process_config)
        if runtime_mode == "async" and gateway_dispatcher_registry is not None:
            gateway_dispatcher_registry.ensure_dispatcher_for_deployment(deployment_instance_id)
    elif action == "reset":
        process_health = supervisor.reset_deployment(process_config)
    else:
        process_health = supervisor.get_health(process_config)
    return _build_detection_runtime_health_response(view, process_health, runtime_mode)


def _build_detection_process_status_response(
    view: DetectionDeploymentInstanceView,
    process_status: DeploymentProcessStatus,
    runtime_mode: str,
) -> DetectionDeploymentProcessStatusResponse:
    """把 deployment 视图与进程状态组合为状态响应。"""

    return DetectionDeploymentProcessStatusResponse(
        deployment_instance_id=view.deployment_instance_id,
        display_name=view.display_name,
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


def _build_detection_runtime_health_response(
    view: DetectionDeploymentInstanceView,
    process_health: DeploymentProcessHealth,
    runtime_mode: str,
) -> DetectionDeploymentRuntimeHealthResponse:
    """把 deployment 视图与进程健康状态组合为详细响应。"""

    return DetectionDeploymentRuntimeHealthResponse(
        deployment_instance_id=view.deployment_instance_id,
        display_name=view.display_name,
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
        instances=[_build_detection_runtime_instance_health_response(item) for item in process_health.instances],
        keep_warm=_build_detection_keep_warm_response(process_health.keep_warm),
        local_buffer_broker=dict(process_health.local_buffer_broker),
    )


def _build_detection_runtime_instance_health_response(
    item: DeploymentProcessInstanceHealth,
) -> DetectionDeploymentRuntimeInstanceHealthResponse:
    """把 runtime 实例健康状态转换为 REST 响应。"""

    return DetectionDeploymentRuntimeInstanceHealthResponse(
        instance_id=item.instance_id,
        healthy=item.healthy,
        warmed=item.warmed,
        busy=item.busy,
        last_error=item.last_error,
    )


def _build_detection_keep_warm_response(
    item: DeploymentProcessKeepWarmStatus | None,
) -> DetectionDeploymentProcessKeepWarmResponse:
    """把 keep-warm 状态转换为 REST 响应。"""

    if item is None:
        return DetectionDeploymentProcessKeepWarmResponse()
    return DetectionDeploymentProcessKeepWarmResponse(
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


def _build_detection_deployment_process_event_response(
    item: DetectionDeploymentProcessEvent,
) -> DetectionDeploymentProcessEventResponse:
    """把 deployment 事件转换为 detection REST 响应。"""

    return DetectionDeploymentProcessEventResponse(
        deployment_instance_id=item.deployment_instance_id,
        runtime_mode=item.runtime_mode,
        sequence=item.sequence,
        event_type=item.event_type,
        created_at=item.created_at,
        message=item.message,
        payload=dict(item.payload),
    )
