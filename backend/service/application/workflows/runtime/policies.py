"""Workflow runtime 执行策略工具。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowExecutionPolicy,
    WorkflowRun,
)


WORKFLOW_RUN_DEFAULT_TRACE_LEVEL = "none"
WORKFLOW_RUN_DEFAULT_RETAIN_TRACE_ENABLED = False
WORKFLOW_RUN_DEFAULT_RETAIN_NODE_RECORDS_ENABLED = False
WORKFLOW_RUN_RECORD_MODE_FULL = "full"
WORKFLOW_RUN_RECORD_MODE_MINIMAL = "minimal"
WORKFLOW_RUN_RECORD_MODE_NONE = "none"
WORKFLOW_RUN_RECORD_MODES = frozenset(
    {
        WORKFLOW_RUN_RECORD_MODE_FULL,
        WORKFLOW_RUN_RECORD_MODE_MINIMAL,
        WORKFLOW_RUN_RECORD_MODE_NONE,
    }
)
WORKFLOW_RUN_DEFAULT_RECORD_MODE = WORKFLOW_RUN_RECORD_MODE_FULL
WORKFLOW_RUN_DEFAULT_RETURN_TIMING_METADATA_ENABLED = False
WORKFLOW_RUN_DEFAULT_RETURN_NODE_TIMINGS_ENABLED = False


@dataclass(frozen=True)
class WorkflowExecutionPolicyCreateRequest:
    """描述一条 WorkflowExecutionPolicy 创建请求。

    字段：
    - project_id：所属 Project id。
    - execution_policy_id：策略 id。
    - display_name：展示名称。
    - policy_kind：策略类型。
    - default_timeout_seconds：默认执行超时秒数。
    - max_run_timeout_seconds：允许的最大执行超时秒数。
    - trace_level：trace 保留级别。
    - retain_node_records_enabled：是否保留 node_records。
    - retain_trace_enabled：是否保留 trace 数据。
    - metadata：附加元数据。
    """

    project_id: str
    execution_policy_id: str
    display_name: str
    policy_kind: str
    default_timeout_seconds: int = 30
    max_run_timeout_seconds: int = 30
    trace_level: str = WORKFLOW_RUN_DEFAULT_TRACE_LEVEL
    retain_node_records_enabled: bool = WORKFLOW_RUN_DEFAULT_RETAIN_NODE_RECORDS_ENABLED
    retain_trace_enabled: bool = WORKFLOW_RUN_DEFAULT_RETAIN_TRACE_ENABLED
    metadata: dict[str, object] | None = None


def normalize_execution_policy_create_request(
    request: WorkflowExecutionPolicyCreateRequest,
) -> WorkflowExecutionPolicyCreateRequest:
    """规范化 WorkflowExecutionPolicy 创建请求。"""

    project_id = request.project_id.strip()
    execution_policy_id = request.execution_policy_id.strip()
    display_name = request.display_name.strip()
    policy_kind = request.policy_kind.strip()
    trace_level = request.trace_level.strip()
    if not project_id:
        raise InvalidRequestError("project_id 不能为空")
    if not execution_policy_id:
        raise InvalidRequestError("execution_policy_id 不能为空")
    if not display_name:
        raise InvalidRequestError("display_name 不能为空")
    if policy_kind not in {"preview-default", "runtime-default"}:
        raise InvalidRequestError("policy_kind 取值无效")
    if request.default_timeout_seconds <= 0:
        raise InvalidRequestError("default_timeout_seconds 必须大于 0")
    if request.max_run_timeout_seconds <= 0:
        raise InvalidRequestError("max_run_timeout_seconds 必须大于 0")
    if request.max_run_timeout_seconds < request.default_timeout_seconds:
        raise InvalidRequestError("max_run_timeout_seconds 不能小于 default_timeout_seconds")
    if not trace_level:
        raise InvalidRequestError("trace_level 不能为空")
    return WorkflowExecutionPolicyCreateRequest(
        project_id=project_id,
        execution_policy_id=execution_policy_id,
        display_name=display_name,
        policy_kind=policy_kind,
        default_timeout_seconds=request.default_timeout_seconds,
        max_run_timeout_seconds=request.max_run_timeout_seconds,
        trace_level=trace_level,
        retain_node_records_enabled=request.retain_node_records_enabled,
        retain_trace_enabled=request.retain_trace_enabled,
        metadata=dict(request.metadata or {}),
    )


def serialize_execution_policy_snapshot(
    execution_policy: WorkflowExecutionPolicy,
) -> dict[str, object]:
    """把 WorkflowExecutionPolicy 序列化为 snapshot JSON。"""

    return {
        "execution_policy_id": execution_policy.execution_policy_id,
        "project_id": execution_policy.project_id,
        "display_name": execution_policy.display_name,
        "policy_kind": execution_policy.policy_kind,
        "default_timeout_seconds": execution_policy.default_timeout_seconds,
        "max_run_timeout_seconds": execution_policy.max_run_timeout_seconds,
        "trace_level": execution_policy.trace_level,
        "retain_node_records_enabled": execution_policy.retain_node_records_enabled,
        "retain_trace_enabled": execution_policy.retain_trace_enabled,
        "created_at": execution_policy.created_at,
        "updated_at": execution_policy.updated_at,
        "created_by": execution_policy.created_by,
        "metadata": dict(execution_policy.metadata),
    }


def apply_execution_policy_metadata(
    metadata: dict[str, object],
    *,
    execution_policy: WorkflowExecutionPolicy | None,
    execution_policy_snapshot_object_key: str | None,
) -> dict[str, object]:
    """把 execution policy 摘要补充到 metadata。"""

    payload = dict(metadata)
    if execution_policy is None:
        return payload
    payload["execution_policy"] = {
        "execution_policy_id": execution_policy.execution_policy_id,
        "policy_kind": execution_policy.policy_kind,
        "trace_level": execution_policy.trace_level,
        "retain_node_records_enabled": execution_policy.retain_node_records_enabled,
        "retain_trace_enabled": execution_policy.retain_trace_enabled,
        "snapshot_object_key": execution_policy_snapshot_object_key,
    }
    return payload


def resolve_effective_timeout_seconds(
    *,
    requested_timeout_seconds: int | None,
    fallback_timeout_seconds: int,
    execution_policy: WorkflowExecutionPolicy | None,
    field_name: str,
) -> int:
    """基于 execution policy 计算最终超时秒数。"""

    effective_timeout_seconds = requested_timeout_seconds or fallback_timeout_seconds
    if execution_policy is None:
        return effective_timeout_seconds
    if requested_timeout_seconds is None:
        return execution_policy.default_timeout_seconds
    if requested_timeout_seconds > execution_policy.max_run_timeout_seconds:
        raise InvalidRequestError(
            f"{field_name} 不能大于 execution policy 限制",
            details={
                field_name: requested_timeout_seconds,
                "max_run_timeout_seconds": execution_policy.max_run_timeout_seconds,
                "execution_policy_id": execution_policy.execution_policy_id,
            },
        )
    return effective_timeout_seconds


def apply_workflow_run_persistence_defaults(
    metadata: dict[str, object],
    *,
    execution_policy: WorkflowExecutionPolicy | None,
) -> dict[str, object]:
    """补齐正式 WorkflowRun 的持久化和诊断默认值。"""

    payload = dict(metadata)
    policy_metadata = dict(execution_policy.metadata) if execution_policy is not None else {}
    if "trace_level" not in payload:
        payload["trace_level"] = (
            execution_policy.trace_level
            if execution_policy is not None
            else WORKFLOW_RUN_DEFAULT_TRACE_LEVEL
        )
    if "retain_trace_enabled" not in payload:
        payload["retain_trace_enabled"] = (
            execution_policy.retain_trace_enabled
            if execution_policy is not None
            else WORKFLOW_RUN_DEFAULT_RETAIN_TRACE_ENABLED
        )
    if "retain_node_records_enabled" not in payload:
        payload["retain_node_records_enabled"] = (
            execution_policy.retain_node_records_enabled
            if execution_policy is not None
            else WORKFLOW_RUN_DEFAULT_RETAIN_NODE_RECORDS_ENABLED
        )
    if "workflow_run_record_mode" not in payload:
        payload["workflow_run_record_mode"] = (
            _normalize_optional_str(_read_optional_text(policy_metadata.get("workflow_run_record_mode")))
            or WORKFLOW_RUN_DEFAULT_RECORD_MODE
        )
    if "return_timing_metadata_enabled" not in payload:
        payload["return_timing_metadata_enabled"] = (
            _read_optional_bool_flag(policy_metadata.get("return_timing_metadata_enabled"))
            or WORKFLOW_RUN_DEFAULT_RETURN_TIMING_METADATA_ENABLED
        )
    if "return_node_timings_enabled" not in payload:
        payload["return_node_timings_enabled"] = (
            _read_optional_bool_flag(policy_metadata.get("return_node_timings_enabled"))
            or WORKFLOW_RUN_DEFAULT_RETURN_NODE_TIMINGS_ENABLED
        )
    return payload


def resolve_workflow_run_record_mode(metadata: dict[str, object]) -> str:
    """读取 WorkflowRun 数据库记录模式。"""

    raw_value = metadata.get("workflow_run_record_mode")
    normalized_value = _normalize_optional_str(_read_optional_text(raw_value))
    if normalized_value is None:
        return WORKFLOW_RUN_DEFAULT_RECORD_MODE
    normalized_value = normalized_value.lower()
    if normalized_value not in WORKFLOW_RUN_RECORD_MODES:
        raise InvalidRequestError(
            "workflow_run_record_mode 取值无效",
            details={
                "workflow_run_record_mode": normalized_value,
                "supported_values": sorted(WORKFLOW_RUN_RECORD_MODES),
            },
        )
    return normalized_value


def should_persist_workflow_run(metadata: dict[str, object]) -> bool:
    """判断本次 WorkflowRun 是否需要写入数据库。"""

    return resolve_workflow_run_record_mode(metadata) != WORKFLOW_RUN_RECORD_MODE_NONE


def should_persist_workflow_run_dispatch_record(metadata: dict[str, object]) -> bool:
    """判断同步调用是否需要先写入 dispatching 记录。"""

    return resolve_workflow_run_record_mode(metadata) == WORKFLOW_RUN_RECORD_MODE_FULL


def should_return_workflow_timing_metadata(metadata: dict[str, object]) -> bool:
    """判断返回结果是否需要包含 timings 诊断字段。"""

    return _read_optional_bool_flag(metadata.get("return_timing_metadata_enabled")) is True


def should_return_workflow_node_timings(metadata: dict[str, object]) -> bool:
    """判断返回结果是否需要包含 node_timings 诊断字段。"""

    return _read_optional_bool_flag(metadata.get("return_node_timings_enabled")) is True


def should_retain_workflow_run_node_records(
    workflow_run: WorkflowRun,
    *,
    execution_policy: WorkflowExecutionPolicy | None,
) -> bool:
    """判断 WorkflowRun 是否需要保留 node_records。"""

    metadata_flag = _read_optional_bool_flag(
        workflow_run.metadata.get("retain_node_records_enabled")
    )
    if metadata_flag is False:
        return False
    if execution_policy is not None and not execution_policy.retain_node_records_enabled:
        return False
    if metadata_flag is True:
        return True
    return bool(execution_policy is not None and execution_policy.retain_node_records_enabled)


def should_retain_workflow_run_trace(workflow_run: WorkflowRun) -> bool:
    """判断 WorkflowRun 是否需要写入 events.json。"""

    metadata = dict(workflow_run.metadata)
    metadata_flag = _read_optional_bool_flag(metadata.get("retain_trace_enabled"))
    if metadata_flag is False:
        return False
    trace_level_value = metadata.get("trace_level")
    trace_level = trace_level_value if isinstance(trace_level_value, str) else None
    if _normalize_optional_str(trace_level) == "none":
        return False
    if metadata_flag is True and trace_level is not None:
        return True
    execution_policy_payload = metadata.get("execution_policy")
    if isinstance(execution_policy_payload, dict):
        execution_policy_flag = _read_optional_bool_flag(
            execution_policy_payload.get("retain_trace_enabled")
        )
        if execution_policy_flag is False:
            return False
        policy_trace_level = execution_policy_payload.get("trace_level")
        normalized_policy_trace_level = (
            policy_trace_level if isinstance(policy_trace_level, str) else None
        )
        if _normalize_optional_str(normalized_policy_trace_level) == "none":
            return False
        if execution_policy_flag is True and normalized_policy_trace_level is not None:
            return True
    return False


def _read_optional_bool_flag(value: object) -> bool | None:
    """读取可由 JSON 或文本传入的布尔开关。"""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if normalized_value in {"true", "1", "yes", "on"}:
            return True
        if normalized_value in {"false", "0", "no", "off"}:
            return False
    return None


def _read_optional_text(value: object) -> str | None:
    """读取可选文本字段。"""

    return value if isinstance(value, str) else None


def _normalize_optional_str(value: str | None) -> str | None:
    """规范化可选字符串字段。"""

    if value is None:
        return None
    normalized_value = value.strip()
    return normalized_value or None
