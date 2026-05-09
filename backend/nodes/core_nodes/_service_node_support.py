"""core service nodes 共享 helper。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass, replace
from typing import Sequence

from backend.nodes.core_nodes._logic_node_support import require_value_payload
from backend.nodes.runtime_support import resolve_image_input
from backend.service.application.deployments.yolox_deployment_service import (
    YoloXDeploymentInstanceView,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessConfig,
    YoloXDeploymentProcessHealth,
    YoloXDeploymentProcessKeepWarmStatus,
    YoloXDeploymentProcessStatus,
    YoloXDeploymentProcessSupervisor,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.application.workflows.service_node_runtime import WorkflowServiceNodeRuntimeContext


def require_workflow_service_node_runtime(
    request: WorkflowNodeExecutionRequest,
) -> WorkflowServiceNodeRuntimeContext:
    """返回当前 workflow 节点执行绑定的 service runtime context。

    参数：
    - request：当前节点执行请求。

    返回：
    - WorkflowServiceNodeRuntimeContext：当前执行绑定的 service runtime context。
    """

    runtime_context = request.runtime_context
    if not isinstance(runtime_context, WorkflowServiceNodeRuntimeContext):
        raise ServiceConfigurationError(
            "当前 service node 缺少 WorkflowServiceNodeRuntimeContext",
            details={
                "node_id": request.node_id,
                "node_type_id": request.node_definition.node_type_id,
            },
        )
    return runtime_context


def build_response_body_output(value: object) -> dict[str, object]:
    """把 dataclass 或字典转换成 response-body.v1 输出。"""

    if is_dataclass(value):
        return {"body": asdict(value)}
    if isinstance(value, dict):
        return {"body": dict(value)}
    raise ServiceConfigurationError(
        "service node 返回值必须是 dataclass 或 dict",
        details={"value_type": type(value).__name__},
    )


def require_str_parameter(request: WorkflowNodeExecutionRequest, name: str) -> str:
    """读取必填字符串参数。"""

    value = request.parameters.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(
            f"参数 {name} 不能为空字符串",
            details={"node_id": request.node_id, "parameter": name},
        )
    return value.strip()


def get_optional_str_parameter(request: WorkflowNodeExecutionRequest, name: str) -> str | None:
    """读取可选字符串参数。"""

    value = request.parameters.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidRequestError(
            f"参数 {name} 必须是字符串",
            details={"node_id": request.node_id, "parameter": name},
        )
    normalized = value.strip()
    return normalized or None


def get_optional_int_parameter(request: WorkflowNodeExecutionRequest, name: str) -> int | None:
    """读取可选整数参数。"""

    value = request.parameters.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRequestError(
            f"参数 {name} 必须是整数",
            details={"node_id": request.node_id, "parameter": name},
        )
    return value


def get_optional_float_parameter(request: WorkflowNodeExecutionRequest, name: str) -> float | None:
    """读取可选浮点参数。"""

    value = request.parameters.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidRequestError(
            f"参数 {name} 必须是数字",
            details={"node_id": request.node_id, "parameter": name},
        )
    return float(value)


def get_optional_bool_parameter(request: WorkflowNodeExecutionRequest, name: str) -> bool | None:
    """读取可选布尔参数。"""

    value = request.parameters.get(name)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise InvalidRequestError(
            f"参数 {name} 必须是布尔值",
            details={"node_id": request.node_id, "parameter": name},
        )
    return value


def get_optional_dict_parameter(
    request: WorkflowNodeExecutionRequest,
    name: str,
) -> dict[str, object]:
    """读取可选对象参数。"""

    value = request.parameters.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidRequestError(
            f"参数 {name} 必须是对象",
            details={"node_id": request.node_id, "parameter": name},
        )
    return {str(key): item for key, item in value.items()}


def get_optional_object_input(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "request",
) -> dict[str, object] | None:
    """读取可选对象 value 输入。

    参数：
    - request：当前节点执行请求。
    - input_name：对象输入端口名称。

    返回：
    - dict[str, object] | None：输入对象值；未提供时返回 None。
    """

    raw_payload = request.input_values.get(input_name)
    if raw_payload is None:
        return None
    object_value = require_value_payload(raw_payload, field_name=input_name)["value"]
    if not isinstance(object_value, dict):
        raise InvalidRequestError(
            f"输入 {input_name} 必须是对象 value payload",
            details={"node_id": request.node_id, "input_name": input_name},
        )
    return {str(key): item for key, item in object_value.items()}


def overlay_parameters_from_object_input(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "request",
) -> WorkflowNodeExecutionRequest:
    """把对象输入中的字段覆盖到当前节点参数上。

    参数：
    - request：当前节点执行请求。
    - input_name：对象输入端口名称。

    返回：
    - WorkflowNodeExecutionRequest：参数已合并的新执行请求。
    """

    input_object = get_optional_object_input(request, input_name=input_name)
    if not input_object:
        return request
    merged_parameters = dict(request.parameters)
    merged_parameters.update(input_object)
    return replace(request, parameters=merged_parameters)


def get_optional_str_tuple_parameter(
    request: WorkflowNodeExecutionRequest,
    name: str,
) -> tuple[str, ...] | None:
    """读取可选字符串数组参数。"""

    value = request.parameters.get(name)
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise InvalidRequestError(
            f"参数 {name} 必须是字符串数组",
            details={"node_id": request.node_id, "parameter": name},
        )
    normalized_values: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise InvalidRequestError(
                f"参数 {name} 的每一项都必须是非空字符串",
                details={"node_id": request.node_id, "parameter": name},
            )
        normalized_values.append(item.strip())
    return tuple(normalized_values)


def get_optional_int_pair_parameter(
    request: WorkflowNodeExecutionRequest,
    name: str,
) -> tuple[int, int] | None:
    """读取可选的两个整数参数。"""

    value = request.parameters.get(name)
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Sequence) or len(value) != 2:
        raise InvalidRequestError(
            f"参数 {name} 必须是长度为 2 的整数数组",
            details={"node_id": request.node_id, "parameter": name},
        )
    first, second = value[0], value[1]
    if isinstance(first, bool) or not isinstance(first, int):
        raise InvalidRequestError(
            f"参数 {name} 的第一个值必须是整数",
            details={"node_id": request.node_id, "parameter": name},
        )
    if isinstance(second, bool) or not isinstance(second, int):
        raise InvalidRequestError(
            f"参数 {name} 的第二个值必须是整数",
            details={"node_id": request.node_id, "parameter": name},
        )
    return (first, second)


def get_optional_image_object_key(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "image",
) -> str | None:
    """读取可选 image-ref 输入并返回 object key。"""

    if request.input_values.get(input_name) is None:
        return None
    _, _, object_key = resolve_image_input(request, input_name=input_name)
    return object_key


def resolve_created_by(request: WorkflowNodeExecutionRequest) -> str | None:
    """解析 service 调用使用的 created_by。"""

    parameter_value = get_optional_str_parameter(request, "created_by")
    if parameter_value is not None:
        return parameter_value
    metadata_value = request.execution_metadata.get("created_by")
    if isinstance(metadata_value, str) and metadata_value.strip():
        return metadata_value.strip()
    return None


def resolve_display_name(request: WorkflowNodeExecutionRequest) -> str:
    """解析 service 调用使用的 display_name。"""

    parameter_value = get_optional_str_parameter(request, "display_name")
    if parameter_value is not None:
        return parameter_value
    metadata_value = request.execution_metadata.get("display_name")
    if isinstance(metadata_value, str) and metadata_value.strip():
        return metadata_value.strip()
    return ""


def require_runtime_mode_parameter(
    request: WorkflowNodeExecutionRequest,
    name: str = "runtime_mode",
) -> str:
    """读取并校验 deployment runtime_mode 参数。"""

    runtime_mode = require_str_parameter(request, name)
    if runtime_mode not in {"sync", "async"}:
        raise InvalidRequestError(
            f"参数 {name} 只能是 sync 或 async",
            details={"node_id": request.node_id, "parameter": name},
        )
    return runtime_mode


def require_running_deployment_process(
    *,
    deployment_process_supervisor: YoloXDeploymentProcessSupervisor,
    process_config: YoloXDeploymentProcessConfig,
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
    deployment_process_supervisor: YoloXDeploymentProcessSupervisor,
    process_config: YoloXDeploymentProcessConfig,
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

    runtime_context = require_workflow_service_node_runtime(request)
    deployment_service = runtime_context.build_deployment_service()
    deployment_instance_id = require_str_parameter(request, "deployment_instance_id")
    runtime_mode = require_runtime_mode_parameter(request)
    deployment_view = deployment_service.get_deployment_instance(deployment_instance_id)
    process_config = deployment_service.resolve_process_config(deployment_instance_id)
    deployment_process_supervisor = runtime_context.require_deployment_process_supervisor(runtime_mode)
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

    runtime_context = require_workflow_service_node_runtime(request)
    deployment_service = runtime_context.build_deployment_service()
    deployment_instance_id = require_str_parameter(request, "deployment_instance_id")
    runtime_mode = require_runtime_mode_parameter(request)
    deployment_view = deployment_service.get_deployment_instance(deployment_instance_id)
    process_config = deployment_service.resolve_process_config(deployment_instance_id)
    deployment_process_supervisor = runtime_context.require_deployment_process_supervisor(runtime_mode)
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
    deployment_view: YoloXDeploymentInstanceView,
    runtime_mode: str,
    process_status: YoloXDeploymentProcessStatus,
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
    deployment_view: YoloXDeploymentInstanceView,
    runtime_mode: str,
    process_health: YoloXDeploymentProcessHealth,
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
    keep_warm_status: YoloXDeploymentProcessKeepWarmStatus | None,
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