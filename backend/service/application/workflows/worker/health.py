"""workflow runtime worker 健康状态和状态消息。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from backend.service.application.errors import ServiceConfigurationError, ServiceError
from backend.service.application.local_buffers import LocalBufferBrokerClient, LocalBufferBrokerEventChannel


@dataclass(frozen=True)
class WorkflowRuntimeWorkerState:
    """描述 workflow runtime worker 返回的当前状态。"""

    observed_state: str
    instance_id: str | None = None
    process_id: int | None = None
    current_run_id: str | None = None
    started_at: str | None = None
    heartbeat_at: str | None = None
    loaded_snapshot_fingerprint: str | None = None
    last_error: str | None = None
    health_summary: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowRuntimeWorkerInstance:
    """描述 workflow runtime 当前可观测到的单个 instance 摘要。"""

    instance_id: str
    workflow_runtime_id: str
    state: str
    process_id: int | None = None
    current_run_id: str | None = None
    started_at: str | None = None
    heartbeat_at: str | None = None
    loaded_snapshot_fingerprint: str | None = None
    last_error: str | None = None
    health_summary: dict[str, object] = field(default_factory=dict)


def build_parent_broker_channel_summary(channel: LocalBufferBrokerEventChannel | None) -> dict[str, object]:
    """构造父进程持有的 broker channel 摘要。"""

    if channel is None:
        return {"configured": False, "channel_id": None}
    return {
        "configured": True,
        "channel_id": channel.channel_id,
        "request_timeout_seconds": channel.request_timeout_seconds,
    }


def build_runtime_health_summary(
    local_buffer_reader: LocalBufferBrokerClient | None,
) -> dict[str, object]:
    """构造 workflow runtime worker 的健康摘要。"""

    return {
        "mode": "single-instance-sync",
        "local_buffer_broker": local_buffer_reader.get_health_summary()
        if local_buffer_reader is not None
        else {"connected": False, "channel_id": None, "recent_error": None},
    }


def build_runtime_state_message(
    *,
    workflow_runtime_id: str,
    observed_state: str,
    instance_id: str | None,
    process_id: int | None,
    current_run_id: str | None,
    started_at: str | None,
    heartbeat_at: str,
    loaded_snapshot_fingerprint: str | None,
    last_error: str | None = None,
    health_summary: dict[str, object] | None = None,
    message_type: str = "runtime-state",
    request_id: str | None = None,
) -> dict[str, object]:
    """构造 runtime-state 消息。"""

    payload = {
        "message_type": message_type,
        "workflow_runtime_id": workflow_runtime_id,
        "observed_state": observed_state,
        "instance_id": instance_id,
        "process_id": process_id,
        "current_run_id": current_run_id,
        "started_at": started_at,
        "heartbeat_at": heartbeat_at,
        "loaded_snapshot_fingerprint": loaded_snapshot_fingerprint,
        "last_error": last_error,
        "health_summary": dict(health_summary or {"mode": "single-instance-sync"}),
    }
    if request_id is not None:
        payload["request_id"] = request_id
    return payload


def deserialize_runtime_state(message: object) -> WorkflowRuntimeWorkerState:
    """把 runtime-state 消息反序列化为父进程可用对象。"""

    if not isinstance(message, dict) or message.get("message_type") not in {"runtime-state", "runtime-heartbeat"}:
        raise ServiceConfigurationError("workflow runtime worker 返回了无效状态消息")
    return WorkflowRuntimeWorkerState(
        observed_state=require_payload_str(message, "observed_state"),
        instance_id=read_optional_str(message, "instance_id"),
        process_id=read_optional_int(message, "process_id"),
        current_run_id=read_optional_str(message, "current_run_id"),
        started_at=read_optional_str(message, "started_at"),
        heartbeat_at=read_optional_str(message, "heartbeat_at"),
        loaded_snapshot_fingerprint=read_optional_str(message, "loaded_snapshot_fingerprint"),
        last_error=read_optional_str(message, "last_error"),
        health_summary=require_payload_dict(message, "health_summary"),
    )


def try_deserialize_runtime_state_message(message: object) -> WorkflowRuntimeWorkerState | None:
    """尝试把 runtime-state 或 runtime-heartbeat 消息解析为 worker 状态。"""

    try:
        return deserialize_runtime_state(message)
    except ServiceError:
        return None


def build_synthetic_runtime_state(
    *,
    previous_state: WorkflowRuntimeWorkerState | None,
    observed_state: str,
    last_error: str,
) -> WorkflowRuntimeWorkerState:
    """基于最后一次已知状态构造一条合成 runtime 状态。"""

    if previous_state is None:
        return WorkflowRuntimeWorkerState(
            observed_state=observed_state,
            heartbeat_at=now_isoformat(),
            last_error=last_error,
            health_summary={"mode": "single-instance-sync"},
        )
    return replace(
        previous_state,
        observed_state=observed_state,
        heartbeat_at=now_isoformat(),
        last_error=last_error,
        health_summary={
            **dict(previous_state.health_summary),
            "heartbeat_status": "timed_out" if "超时" in last_error else "process_exited",
        },
    )


def build_runtime_instance_id(workflow_runtime_id: str) -> str:
    """构造单实例 runtime 使用的稳定 instance_id。"""

    return f"{workflow_runtime_id}-primary"


def require_payload_str(payload: object, field_name: str) -> str:
    """从字典负载中读取必填字符串字段。"""

    if not isinstance(payload, dict):
        raise ServiceConfigurationError("workflow runtime worker 负载格式无效")
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ServiceConfigurationError(
            "workflow runtime worker 负载缺少有效字符串字段",
            details={"field_name": field_name},
        )
    return value.strip()


def require_payload_dict(payload: object, field_name: str) -> dict[str, object]:
    """从字典负载中读取对象字段。"""

    if not isinstance(payload, dict):
        raise ServiceConfigurationError("workflow runtime worker 负载格式无效")
    value = payload.get(field_name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ServiceConfigurationError(
            "workflow runtime worker 负载缺少有效对象字段",
            details={"field_name": field_name},
        )
    return {str(key): item for key, item in value.items()}


def read_optional_str(payload: object, field_name: str) -> str | None:
    """从字典负载中读取可选字符串字段。"""

    if not isinstance(payload, dict):
        return None
    value = payload.get(field_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def read_optional_int(payload: object, field_name: str) -> int | None:
    """从字典负载中读取可选整数字段。"""

    if not isinstance(payload, dict):
        return None
    value = payload.get(field_name)
    if isinstance(value, int):
        return value
    return None


def now_isoformat() -> str:
    """返回当前 UTC 时间的 ISO8601 文本。"""

    from datetime import datetime, timezone  # noqa: PLC0415

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
