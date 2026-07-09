"""workflow runtime worker 命令和执行结果消息。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from multiprocessing.queues import Queue
from pathlib import Path
from threading import Event
from typing import Any
import multiprocessing

from backend.service.application.errors import OperationTimeoutError, ServiceConfigurationError, ServiceError
from backend.service.application.workflows.runtime_payload_sanitizer import (
    serialize_node_execution_record_for_response,
)
from backend.service.application.workflows.worker.health import (
    WorkflowRuntimeWorkerState,
    now_isoformat,
    read_optional_int,
    read_optional_str,
    require_payload_dict,
    require_payload_str,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class WorkflowRuntimeWorkerRunResult:
    """描述 workflow runtime worker 返回的一次同步调用结果。"""

    state: str
    outputs: dict[str, object] = field(default_factory=dict)
    template_outputs: dict[str, object] = field(default_factory=dict)
    node_records: tuple[dict[str, object], ...] = ()
    error_message: str | None = None
    error_details: dict[str, object] = field(default_factory=dict)
    timings: dict[str, object] = field(default_factory=dict)
    worker_state: WorkflowRuntimeWorkerState = field(
        default_factory=lambda: WorkflowRuntimeWorkerState(observed_state="failed")
    )


@dataclass(frozen=True)
class WorkflowRuntimeAsyncRunCallbacks:
    """描述异步 WorkflowRun 在线程中的状态回写回调。"""

    on_started: Callable[[], None]
    on_completed: Callable[[WorkflowRuntimeWorkerRunResult], None]
    on_cancelled: Callable[[WorkflowRuntimeWorkerState | None], None]
    on_failed: Callable[[ServiceError], None]
    on_timed_out: Callable[[OperationTimeoutError], None]


@dataclass
class WorkflowRuntimePendingResponse:
    """描述一条等待中的 worker 响应。"""

    event: Event = field(default_factory=Event)
    response: dict[str, object] | None = None
    error_message: str | None = None


def build_worker_error_message(
    *,
    workflow_runtime_id: str,
    workflow_run_id: str | None,
    request_id: str | None,
    error_message: str,
    error_details: dict[str, object],
    state: str,
    instance_id: str | None,
    current_run_id: str | None,
    started_at: str | None,
    loaded_snapshot_fingerprint: str | None,
    observed_state: str = "failed",
    worker_last_error: str | None = None,
    health_summary: dict[str, object] | None = None,
) -> dict[str, object]:
    """构造 worker-error 消息。"""

    payload = {
        "message_type": "worker-error",
        "workflow_runtime_id": workflow_runtime_id,
        "workflow_run_id": workflow_run_id,
        "state": state,
        "error_message": error_message,
        "error_details": dict(error_details),
        "worker_state": {
            "observed_state": observed_state,
            "instance_id": instance_id,
            "process_id": multiprocessing.current_process().pid,
            "current_run_id": current_run_id,
            "started_at": started_at,
            "heartbeat_at": now_isoformat(),
            "loaded_snapshot_fingerprint": loaded_snapshot_fingerprint,
            "last_error": error_message if worker_last_error is None and observed_state == "failed" else worker_last_error,
            "health_summary": dict(health_summary or {"mode": "single-instance-sync"}),
        },
    }
    if request_id is not None:
        payload["request_id"] = request_id
    return payload


def deserialize_run_result(message: object) -> WorkflowRuntimeWorkerRunResult:
    """把 worker run 结果反序列化为父进程可用对象。"""

    if not isinstance(message, dict):
        raise ServiceConfigurationError("workflow runtime worker 返回了无效执行消息")
    message_type = str(message.get("message_type") or "")
    if message_type not in {"run-result", "worker-error"}:
        raise ServiceConfigurationError(
            "workflow runtime worker 返回了未支持的执行消息类型",
            details={"message_type": message_type},
        )
    worker_state_payload = message.get("worker_state") if isinstance(message.get("worker_state"), dict) else {}
    worker_state = WorkflowRuntimeWorkerState(
        observed_state=str(worker_state_payload.get("observed_state") or "failed"),
        instance_id=read_optional_str(worker_state_payload, "instance_id"),
        process_id=read_optional_int(worker_state_payload, "process_id"),
        current_run_id=read_optional_str(worker_state_payload, "current_run_id"),
        started_at=read_optional_str(worker_state_payload, "started_at"),
        heartbeat_at=read_optional_str(worker_state_payload, "heartbeat_at"),
        loaded_snapshot_fingerprint=read_optional_str(worker_state_payload, "loaded_snapshot_fingerprint"),
        last_error=read_optional_str(worker_state_payload, "last_error"),
        health_summary=require_payload_dict(worker_state_payload, "health_summary"),
    )
    return WorkflowRuntimeWorkerRunResult(
        state=str(message.get("state") or "failed"),
        outputs=require_payload_dict(message, "outputs"),
        template_outputs=require_payload_dict(message, "template_outputs"),
        node_records=tuple(dict(item) for item in (message.get("node_records") or []) if isinstance(item, dict)),
        error_message=read_optional_str(message, "error_message"),
        error_details=require_payload_dict(message, "error_details"),
        timings=require_payload_dict(message, "timings"),
        worker_state=worker_state,
    )


def try_deserialize_run_result_worker_state(message: object) -> WorkflowRuntimeWorkerState | None:
    """尝试从 run-result 或 worker-error 中提取 worker_state。"""

    try:
        return deserialize_run_result(message).worker_state
    except ServiceError:
        return None


def serialize_node_records(
    node_records: tuple[dict[str, object], ...] | tuple[Any, ...],
    *,
    retain_payloads: bool = True,
) -> tuple[dict[str, object], ...]:
    """把节点执行记录统一转换为 JSON 可序列化字典。

    参数：
    - node_records：节点执行记录。
    - retain_payloads：是否保留 inputs/outputs 载荷；高速调用关闭后只返回节点耗时摘要，
      避免图片、base64 和中间结果在 worker/父进程之间重复序列化。
    """

    serialized: list[dict[str, object]] = []
    for item in node_records:
        if retain_payloads:
            serialized.append(serialize_node_execution_record_for_response(item))
            continue
        serialized.append(_serialize_compact_node_record(item))
    return tuple(serialized)


def _serialize_compact_node_record(item: object) -> dict[str, object]:
    """把节点执行记录压缩为只含定位信息和耗时的轻量结构。"""

    if isinstance(item, dict):
        return {
            "node_id": read_optional_str(item, "node_id") or "",
            "node_type_id": read_optional_str(item, "node_type_id") or "",
            "runtime_kind": read_optional_str(item, "runtime_kind") or "",
            "duration_ms": _read_optional_float(item.get("duration_ms")),
            "inputs": {},
            "outputs": {},
        }
    return {
        "node_id": str(getattr(item, "node_id", "") or ""),
        "node_type_id": str(getattr(item, "node_type_id", "") or ""),
        "runtime_kind": str(getattr(item, "runtime_kind", "") or ""),
        "duration_ms": _read_optional_float(getattr(item, "duration_ms", None)),
        "inputs": {},
        "outputs": {},
    }


def _read_optional_float(value: object) -> float | None:
    """读取可选 float 字段，过滤 bool 这类 int 子类值。"""

    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def read_message_type(payload: object) -> str:
    """读取命令消息类型。"""

    return require_payload_str(payload, "message_type")


def read_timeout_seconds(payload: object) -> int:
    """读取命令里的超时秒数。"""

    if not isinstance(payload, dict):
        raise ServiceConfigurationError("workflow runtime worker 命令负载格式无效")
    value = payload.get("requested_timeout_seconds")
    if isinstance(value, int) and value > 0:
        return value
    return 60


def read_heartbeat_interval_seconds(payload: object) -> float:
    """读取 runtime_payload 里的 heartbeat 周期秒数。"""

    if not isinstance(payload, dict):
        return 5.0
    value = payload.get("heartbeat_interval_seconds")
    if isinstance(value, int) and value > 0:
        return float(value)
    if isinstance(value, float) and value > 0:
        return float(value)
    return 5.0


def read_project_id_from_snapshot(
    *,
    dataset_storage: LocalDatasetStorage,
    application_snapshot_object_key: str,
) -> str:
    """从 application snapshot 中读取 project_id。"""

    payload = dataset_storage.read_json(application_snapshot_object_key)
    metadata = payload.get("metadata") if isinstance(payload, dict) else {}
    if isinstance(metadata, dict):
        project_id = metadata.get("project_id")
        if isinstance(project_id, str) and project_id.strip():
            return project_id.strip()
    raise ServiceConfigurationError("workflow runtime application snapshot 缺少 project_id metadata")


def resolve_database_url(database_url: str) -> str:
    """把 SQLite 文件数据库 URL 规范化为绝对路径。"""

    from sqlalchemy.engine import URL, make_url  # noqa: PLC0415

    parsed_url: URL = make_url(database_url)
    if parsed_url.drivername != "sqlite" or parsed_url.database in (None, ":memory:"):
        return database_url
    resolved_database_path = Path(parsed_url.database).resolve()
    return parsed_url.set(database=resolved_database_path.as_posix()).render_as_string(hide_password=False)


def resolve_backend_service_settings(settings: Any) -> Any:
    """把 backend-service settings 规范化为适合子进程复用的绝对路径版本。"""

    from backend.service.settings import BackendServiceSettings  # noqa: PLC0415

    normalized_settings = BackendServiceSettings.model_validate(settings.model_dump(mode="python"))
    normalized_settings.database.url = resolve_database_url(normalized_settings.database.url)
    normalized_settings.dataset_storage.root_dir = str(Path(normalized_settings.dataset_storage.root_dir).resolve())
    normalized_settings.queue.root_dir = str(Path(normalized_settings.queue.root_dir).resolve())
    normalized_settings.custom_nodes.root_dir = str(Path(normalized_settings.custom_nodes.root_dir).resolve())
    return normalized_settings


def drain_queue(queue: Queue[Any]) -> None:
    """关闭 multiprocessing queue 并等待后台线程退出。"""

    queue.close()
    queue.join_thread()
