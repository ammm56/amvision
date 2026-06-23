"""deployment 子进程动作 helper。"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from backend.nodes.core_nodes.support.service.builders import build_service_node_deployment_service
from backend.nodes.core_nodes.support.service.context import require_workflow_service_node_runtime
from backend.nodes.core_nodes.support.service.parameters import (
    overlay_parameters_from_object_input,
    require_runtime_mode_parameter,
    require_service_task_type_parameter,
    require_str_parameter,
)
from backend.nodes.core_nodes.support.service.responses import build_response_body_output
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest

if TYPE_CHECKING:
    from backend.service.application.deployments.deployment_instance_service import (
        DeploymentInstanceView,
    )
    from backend.service.application.runtime.deployment.deployment_process_supervisor import (
        DeploymentProcessConfig,
        DeploymentProcessHealth,
        DeploymentProcessKeepWarmStatus,
        DeploymentProcessStatus,
        DeploymentProcessSupervisor,
    )


def require_running_deployment_process(
    *,
    deployment_process_supervisor: DeploymentProcessSupervisor,
    process_config: DeploymentProcessConfig,
    runtime_mode: str,
) -> None:
    """校验当前 deployment 子进程已经处于 running 状态。"""

    status = deployment_process_supervisor.get_status(process_config)
    if status.process_state == "running":
        return
    raise InvalidRequestError(
        "当前 deployment 进程尚未启动，请先调用 start 或 warmup 接口",
        details={
            "deployment_instance_id": process_config.deployment_instance_id,
            "runtime_mode": runtime_mode,
            "process_state": status.process_state,
            "required_actions": [f"{runtime_mode}/start", f"{runtime_mode}/warmup"],
        },
    )


def ensure_running_deployment_process(
    *,
    deployment_process_supervisor: DeploymentProcessSupervisor,
    process_config: DeploymentProcessConfig,
    runtime_mode: str,
    auto_start_process: bool,
) -> None:
    """确保当前 deployment 子进程已经处于 running 状态。

    参数：
    - deployment_process_supervisor：当前运行时通道对应的 deployment supervisor。
    - process_config：deployment 子进程配置。
    - runtime_mode：当前运行时通道；sync 或 async。
    - auto_start_process：当前 workflow 节点是否允许在未启动时自动拉起子进程。
    """

    if auto_start_process:
        status = deployment_process_supervisor.get_status(process_config)
        if status.process_state != "running":
            deployment_process_supervisor.start_deployment(process_config)
    require_running_deployment_process(
        deployment_process_supervisor=deployment_process_supervisor,
        process_config=process_config,
        runtime_mode=runtime_mode,
    )


def run_deployment_process_status_action(
    request: WorkflowNodeExecutionRequest,
    *,
    action: str,
) -> dict[str, object]:
    """执行 deployment 进程状态动作，并返回对齐 API 的 body。"""

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    task_type = require_service_task_type_parameter(request)
    deployment_service = build_service_node_deployment_service(
        runtime_context,
        task_type=task_type,
    )
    deployment_instance_id = require_str_parameter(request, "deployment_instance_id")
    runtime_mode = require_runtime_mode_parameter(request)
    deployment_view = deployment_service.get_deployment_instance(deployment_instance_id)
    process_config = deployment_service.resolve_process_config(deployment_instance_id)
    deployment_process_supervisor = runtime_context.require_deployment_process_supervisor(
        task_type=task_type,
        runtime_mode=runtime_mode,
    )
    if action == "start":
        process_status = deployment_process_supervisor.start_deployment(process_config)
    elif action == "stop":
        process_status = deployment_process_supervisor.stop_deployment(process_config)
    elif action == "status":
        process_status = deployment_process_supervisor.get_status(process_config)
    else:
        raise ServiceConfigurationError(
            "当前 deployment 状态动作不受支持",
            details={"action": action},
        )
    return build_response_body_output(
        _build_deployment_process_status_body(
            deployment_view=deployment_view,
            runtime_mode=runtime_mode,
            process_status=process_status,
        )
    )


def run_deployment_process_health_action(
    request: WorkflowNodeExecutionRequest,
    *,
    action: str,
) -> dict[str, object]:
    """执行 deployment 进程健康动作，并返回对齐 API 的 body。"""

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    task_type = require_service_task_type_parameter(request)
    deployment_service = build_service_node_deployment_service(
        runtime_context,
        task_type=task_type,
    )
    deployment_instance_id = require_str_parameter(request, "deployment_instance_id")
    runtime_mode = require_runtime_mode_parameter(request)
    deployment_view = deployment_service.get_deployment_instance(deployment_instance_id)
    process_config = deployment_service.resolve_process_config(deployment_instance_id)
    deployment_process_supervisor = runtime_context.require_deployment_process_supervisor(
        task_type=task_type,
        runtime_mode=runtime_mode,
    )
    if action == "warmup":
        process_health = deployment_process_supervisor.warmup_deployment(process_config)
    elif action == "reset":
        process_health = deployment_process_supervisor.reset_deployment(process_config)
    elif action == "health":
        process_health = deployment_process_supervisor.get_health(process_config)
    else:
        raise ServiceConfigurationError(
            "当前 deployment 健康动作不受支持",
            details={"action": action},
        )
    return build_response_body_output(
        _build_deployment_process_health_body(
            deployment_view=deployment_view,
            runtime_mode=runtime_mode,
            process_health=process_health,
        )
    )


def _build_deployment_process_status_body(
    *,
    deployment_view: DeploymentInstanceView,
    runtime_mode: str,
    process_status: DeploymentProcessStatus,
) -> dict[str, object]:
    """构建对齐 deployment status API 的 body。"""

    return {
        "deployment_instance_id": deployment_view.deployment_instance_id,
        "display_name": deployment_view.display_name,
        "runtime_mode": runtime_mode,
        "desired_state": process_status.desired_state,
        "process_state": process_status.process_state,
        "process_id": process_status.process_id,
        "auto_restart": process_status.auto_restart,
        "restart_count": process_status.restart_count,
        "restart_count_rollover_count": process_status.restart_count_rollover_count,
        "last_exit_code": process_status.last_exit_code,
        "last_error": process_status.last_error,
        "instance_count": process_status.instance_count,
    }


def _build_deployment_process_health_body(
    *,
    deployment_view: DeploymentInstanceView,
    runtime_mode: str,
    process_health: DeploymentProcessHealth,
) -> dict[str, object]:
    """构建对齐 deployment health API 的 body。"""

    return {
        "deployment_instance_id": deployment_view.deployment_instance_id,
        "display_name": deployment_view.display_name,
        "runtime_mode": runtime_mode,
        "desired_state": process_health.desired_state,
        "process_state": process_health.process_state,
        "process_id": process_health.process_id,
        "auto_restart": process_health.auto_restart,
        "restart_count": process_health.restart_count,
        "restart_count_rollover_count": process_health.restart_count_rollover_count,
        "last_exit_code": process_health.last_exit_code,
        "last_error": process_health.last_error,
        "instance_count": process_health.instance_count,
        "healthy_instance_count": process_health.healthy_instance_count,
        "warmed_instance_count": process_health.warmed_instance_count,
        "pinned_output_total_bytes": process_health.pinned_output_total_bytes,
        "instances": [asdict(item) for item in process_health.instances],
        "keep_warm": _build_keep_warm_body(process_health.keep_warm),
    }


def _build_keep_warm_body(
    keep_warm_status: DeploymentProcessKeepWarmStatus | None,
) -> dict[str, object]:
    """构建 keep-warm 状态 body。"""

    if keep_warm_status is None:
        return {
            "enabled": False,
            "activated": False,
            "paused": False,
            "idle": True,
            "interval_seconds": 0.0,
            "yield_timeout_seconds": 0.0,
            "success_count": 0,
            "success_count_rollover_count": 0,
            "error_count": 0,
            "error_count_rollover_count": 0,
            "last_error": None,
        }
    return asdict(keep_warm_status)
