"""现有 worker 的点云入口：私有交接身份、一次映射及 Scope 内引用。"""

from dataclasses import dataclass

from backend.contracts.workflows.point_cloud_trigger import WorkflowTriggerCloudInputV1
from backend.contracts.workflows.profile_trigger import (
    PROFILE_INPUT_FORMAT,
    WorkflowTriggerProfileInputV1,
)
from backend.contracts.workflows.raster_trigger import (
    RASTER_INPUT_FORMAT,
    WorkflowTriggerRasterInputV1,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.workflows.execution.execution_control import (
    ExecutionControl,
    prepare_execution_control_metadata,
)


CLOUD_HANDOFF_KEY = "_workflow_cloud_input_handoff"


@dataclass(frozen=True)
class CloudInputHandoff:
    """只由 supervisor 创建，经现有私有 multiprocessing Queue 交给 worker。

    JSON 元数据无法伪造该对象；不在数据库或公开结果中保留它。
    """

    run_id: str
    binding_ids: tuple[str, ...]
    payload: dict[str, object]


def trusted_cloud_bindings(metadata, bindings):
    """校验本次 run 与布局快照，拒绝字典冒充私有交接。"""
    handoff = metadata.get(CLOUD_HANDOFF_KEY)
    if handoff is None:
        return frozenset()
    if (
        not isinstance(handoff, CloudInputHandoff)
        or handoff.run_id != metadata.get("workflow_run_id")
        or not handoff.binding_ids
        or any(bindings.get(key) != handoff.payload for key in handoff.binding_ids)
    ):
        raise InvalidRequestError("点云输入缺少当前运行的有效交接身份")
    _input_model(handoff.payload).model_validate(handoff.payload)
    return frozenset(handoff.binding_ids)


def _input_model(payload):
    """按显式格式分发；不在某种输入验证失败后尝试另一种。"""
    if payload.get("format_id") == PROFILE_INPUT_FORMAT:
        return WorkflowTriggerProfileInputV1
    return (
        WorkflowTriggerRasterInputV1
        if payload.get("format_id") == RASTER_INPUT_FORMAT
        else WorkflowTriggerCloudInputV1
    )


def require_raster_handoff(metadata, value):
    """节点仅消费本次受信交接的固定正文，JSON、旧 run 和替换标定均拒绝。"""
    return _require_handoff(metadata, value, WorkflowTriggerRasterInputV1)


def require_profile_handoff(metadata, value):
    """轮廓使用相同的本次运行交接，不接受调用方 JSON 定位。"""
    return _require_handoff(metadata, value, WorkflowTriggerProfileInputV1)


def _require_handoff(metadata, value, model):
    """私有身份与完整正文共同校验，格式仍由节点显式指定。"""
    handoff = metadata.get(CLOUD_HANDOFF_KEY)
    if (
        not isinstance(handoff, CloudInputHandoff)
        or handoff.run_id != metadata.get("workflow_run_id")
        or not handoff.binding_ids
        or value != handoff.payload
    ):
        raise InvalidRequestError("标定数组缺少当前运行的有效交接身份")
    return model.model_validate(value)


def materialize_cloud_bindings(*, metadata, bindings, context, scope, cancellation):
    """只读映射一次；同一输入的多个图分支共享原始行号和同一生命周期。"""
    keys = trusted_cloud_bindings(metadata, bindings)
    if not keys:
        return bindings
    if _input_model(metadata[CLOUD_HANDOFF_KEY].payload) in (
        WorkflowTriggerRasterInputV1,
        WorkflowTriggerProfileInputV1,
    ):
        # 标定数组转点云由公开节点执行，不提前投影或创建额外资源。
        return bindings
    from backend.service.application.workflows.point_cloud.runtime import (
        get_cloud_runtime,
    )

    policy = context.point_cloud_policy
    reader = context.local_buffer_reader
    if policy is None or reader is None:
        raise ServiceConfigurationError("同机点云输入缺少显式策略或 LocalBuffer reader")
    payload = WorkflowTriggerCloudInputV1.model_validate(
        metadata[CLOUD_HANDOFF_KEY].payload
    )
    control = ExecutionControl(
        node_id="app-input",
        cancellation_event=cancellation,
        deadline_monotonic=prepare_execution_control_metadata(metadata),
        deadline_scope="workflow",
    )
    runtime = get_cloud_runtime(
        scope, run_id=metadata["workflow_run_id"], policy=policy.io
    )
    ref = runtime.open_local(
        descriptor=payload.descriptor,
        expected_descriptor_sha256=payload.descriptor_sha256,
        acquire_view=lambda: reader.acquire_buffer_ref_view(payload.buffer_ref),
        cancel=control.raise_if_cancelled_or_expired,
    ).model_dump(mode="json")
    return {key: ref if key in keys else value for key, value in bindings.items()}
