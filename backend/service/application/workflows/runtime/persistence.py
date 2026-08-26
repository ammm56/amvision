"""WorkflowRun 持久化辅助。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock

from backend.contracts.buffers import BufferRef
from backend.contracts.workflows.resource_semantics import build_workflow_run_events_object_key
from backend.service.application.workflows.execution_cleanup import register_local_buffer_lease_cleanup
from backend.service.application.workflows.runtime.policies import (
    should_retain_workflow_run_node_records,
    should_retain_workflow_run_trace,
    should_return_workflow_timing_metadata,
)
from backend.service.application.workflows.runtime_payload_sanitizer import (
    sanitize_runtime_mapping,
    serialize_node_execution_record,
)
from backend.service.application.workflows.worker.messages import WorkflowRuntimeWorkerRunResult
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowExecutionPolicy,
    WorkflowRun,
    WorkflowRunEvent,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


WORKFLOW_RUN_LIFECYCLE_EVENT_TYPES = frozenset(
    {
        "run.queued",
        "run.running",
        "run.started",
        "run.succeeded",
        "run.failed",
        "run.cancelled",
        "run.timed_out",
    }
)
"""不受 trace 开关影响、始终持久化的 WorkflowRun 生命周期事件。"""

WORKFLOW_RUN_TERMINAL_EVENT_TYPES = frozenset(
    {
        "run.succeeded",
        "run.failed",
        "run.cancelled",
        "run.timed_out",
    }
)
"""WorkflowRun 终态事件；写入后可以释放进程内 sequence 缓存。"""

_JSONL_TAIL_READ_CHUNK_SIZE = 64 * 1024


def apply_workflow_run_result(
    workflow_run: WorkflowRun,
    worker_result: WorkflowRuntimeWorkerRunResult,
    *,
    execution_policy: WorkflowExecutionPolicy | None = None,
) -> WorkflowRun:
    """把 worker 返回的执行结果回写到 WorkflowRun。"""

    metadata = dict(workflow_run.metadata)
    if worker_result.error_details:
        metadata["error_details"] = dict(worker_result.error_details)
    if worker_result.timings and should_return_workflow_timing_metadata(metadata):
        metadata["timings"] = _merge_timing_metadata(metadata.get("timings"), worker_result.timings)
    retain_outputs_enabled = _read_optional_bool_flag(metadata.get("retain_outputs_enabled")) is not False
    return replace(
        workflow_run,
        state=worker_result.state,
        started_at=workflow_run.started_at or _now_isoformat(),
        finished_at=_now_isoformat(),
        assigned_process_id=worker_result.worker_state.process_id,
        outputs=sanitize_runtime_mapping(worker_result.outputs) if retain_outputs_enabled else {},
        template_outputs=sanitize_runtime_mapping(worker_result.template_outputs) if retain_outputs_enabled else {},
        node_records=_serialize_node_records(
            tuple(worker_result.node_records),
            retain_node_records_enabled=should_retain_workflow_run_node_records(
                workflow_run,
                execution_policy=execution_policy,
            ),
        ),
        error_message=worker_result.error_message,
        metadata=metadata,
    )


def with_input_buffer_ref_cleanups(
    execution_metadata: dict[str, object],
    input_bindings: dict[str, object],
) -> dict[str, object]:
    """把输入里的 BufferRef lease 登记为执行期 cleanup。"""

    payload = dict(execution_metadata)
    for buffer_ref in _iter_input_buffer_refs(input_bindings):
        register_local_buffer_lease_cleanup(
            payload,
            lease_id=buffer_ref.lease_id,
        )
    return payload


def append_workflow_run_event(
    *,
    dataset_storage: LocalDatasetStorage,
    workflow_run: WorkflowRun,
    event_lock: Lock,
    event_sequences: dict[str, int],
    event_sequence_lock: Lock,
    event_type: str,
    message: str,
    payload: dict[str, object] | None = None,
) -> WorkflowRunEvent:
    """按 WorkflowRun 保留策略直接追加一行 events.jsonl。

    生命周期事件始终写入；节点和诊断事件仍由 trace 策略控制。sequence
    在进程内缓存，服务重启后的首次追加只从文件尾恢复最后一个有效序号。
    """

    normalized_event_type = event_type.strip() or "run.updated"
    if (
        normalized_event_type not in WORKFLOW_RUN_LIFECYCLE_EVENT_TYPES
        and not should_retain_workflow_run_trace(workflow_run)
    ):
        return WorkflowRunEvent(
            workflow_run_id=workflow_run.workflow_run_id,
            workflow_runtime_id=workflow_run.workflow_runtime_id,
            sequence=0,
            event_type=normalized_event_type,
            created_at=_now_isoformat(),
            message=message.strip() or "workflow run 事件",
            payload={},
        )

    event_payload = sanitize_runtime_mapping(
        {
            **build_workflow_run_event_payload(workflow_run),
            **dict(payload or {}),
        }
    )
    with event_lock:
        events_path = dataset_storage.resolve(
            build_workflow_run_events_object_key(workflow_run.workflow_run_id)
        )
        sequence_key = str(events_path.resolve())
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with event_sequence_lock:
            last_sequence = event_sequences.get(sequence_key)
        if last_sequence is None:
            _ensure_jsonl_append_boundary(events_path)
            last_sequence = _read_last_valid_workflow_run_event_sequence(
                events_path,
                workflow_run_id=workflow_run.workflow_run_id,
            )
        sequence = last_sequence + 1
        event = WorkflowRunEvent(
            workflow_run_id=workflow_run.workflow_run_id,
            workflow_runtime_id=workflow_run.workflow_runtime_id,
            sequence=sequence,
            event_type=normalized_event_type,
            created_at=_now_isoformat(),
            message=message.strip() or "workflow run 事件",
            payload=event_payload,
        )
        with events_path.open("ab") as event_stream:
            event_stream.write(
                json.dumps(
                    _serialize_workflow_run_event(event),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
        with event_sequence_lock:
            event_sequences[sequence_key] = sequence
    return event


def read_workflow_run_events(
    dataset_storage: LocalDatasetStorage,
    workflow_run_id: str,
) -> tuple[WorkflowRunEvent, ...]:
    """读取一条 WorkflowRun 的全部事件。"""

    object_key = build_workflow_run_events_object_key(workflow_run_id)
    if not dataset_storage.resolve(object_key).exists():
        return ()
    events: list[WorkflowRunEvent] = []
    with dataset_storage.resolve(object_key).open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as event_stream:
        for line in event_stream:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = _deserialize_workflow_run_event(workflow_run_id, item)
            if event is not None:
                events.append(event)
    return tuple(events)


def release_workflow_run_event_sequence(
    *,
    dataset_storage: LocalDatasetStorage,
    workflow_run_id: str,
    event_sequences: dict[str, int],
    event_sequence_lock: Lock,
) -> None:
    """释放已终止 WorkflowRun 的进程内 sequence，避免长期运行持续增长。"""

    events_path = dataset_storage.resolve(
        build_workflow_run_events_object_key(workflow_run_id)
    )
    with event_sequence_lock:
        event_sequences.pop(str(events_path.resolve()), None)


def _deserialize_workflow_run_event(
    workflow_run_id: str,
    value: object,
) -> WorkflowRunEvent | None:
    """把一行 JSON 字典转换为 WorkflowRunEvent，无效行返回 None。"""

    if not isinstance(value, dict):
        return None
    sequence = value.get("sequence")
    created_at = value.get("created_at")
    event_type = value.get("event_type")
    message = value.get("message")
    workflow_runtime_id = value.get("workflow_runtime_id")
    if (
        not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence <= 0
        or not isinstance(created_at, str)
        or not created_at
        or not isinstance(event_type, str)
        or not event_type
        or not isinstance(message, str)
        or not message
        or not isinstance(workflow_runtime_id, str)
        or not workflow_runtime_id
    ):
        return None
    payload_value = value.get("payload") if isinstance(value.get("payload"), dict) else {}
    return WorkflowRunEvent(
        workflow_run_id=workflow_run_id,
        workflow_runtime_id=workflow_runtime_id,
        sequence=sequence,
        event_type=event_type,
        created_at=created_at,
        message=message,
        payload=payload_value,
    )


def _read_last_valid_workflow_run_event_sequence(
    events_path: Path,
    *,
    workflow_run_id: str,
) -> int:
    """从 JSONL 文件尾向前读取最后一个有效 WorkflowRun 事件序号。"""

    if not events_path.is_file():
        return 0
    with events_path.open("rb") as event_stream:
        event_stream.seek(0, 2)
        position = event_stream.tell()
        suffix = b""
        while position > 0:
            read_size = min(_JSONL_TAIL_READ_CHUNK_SIZE, position)
            position -= read_size
            event_stream.seek(position)
            chunk = event_stream.read(read_size) + suffix
            lines = chunk.split(b"\n")
            suffix = lines[0]
            for raw_line in reversed(lines[1:]):
                sequence = _read_workflow_run_event_sequence_from_line(
                    raw_line,
                    workflow_run_id=workflow_run_id,
                )
                if sequence is not None:
                    return sequence
        sequence = _read_workflow_run_event_sequence_from_line(
            suffix,
            workflow_run_id=workflow_run_id,
        )
        return sequence or 0


def _read_workflow_run_event_sequence_from_line(
    raw_line: bytes,
    *,
    workflow_run_id: str,
) -> int | None:
    """解析单行并返回有效 WorkflowRun 事件序号。"""

    if not raw_line.strip():
        return None
    try:
        value = json.loads(raw_line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    event = _deserialize_workflow_run_event(workflow_run_id, value)
    return event.sequence if event is not None else None


def _ensure_jsonl_append_boundary(events_path: Path) -> None:
    """为异常退出留下的 JSONL 半行补换行，确保后续事件保持独立。"""

    if not events_path.is_file() or events_path.stat().st_size == 0:
        return
    with events_path.open("rb+") as event_stream:
        event_stream.seek(-1, 2)
        if event_stream.read(1) != b"\n":
            event_stream.seek(0, 2)
            event_stream.write(b"\n")


def _serialize_workflow_run_event(event: WorkflowRunEvent) -> dict[str, object]:
    """把一条 WorkflowRun 事件转换成 JSONL 字典。"""

    return {
        "workflow_run_id": event.workflow_run_id,
        "workflow_runtime_id": event.workflow_runtime_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "created_at": event.created_at,
        "message": event.message,
        "payload": sanitize_runtime_mapping(event.payload),
    }


def build_workflow_run_event_payload(workflow_run: WorkflowRun) -> dict[str, object]:
    """构造 WorkflowRun 事件的基础 payload。"""

    payload: dict[str, object] = {
        "state": workflow_run.state,
        "workflow_runtime_id": workflow_run.workflow_runtime_id,
    }
    if workflow_run.assigned_process_id is not None:
        payload["assigned_process_id"] = workflow_run.assigned_process_id
    if workflow_run.error_message is not None:
        payload["error_message"] = workflow_run.error_message
    if workflow_run.started_at is not None:
        payload["started_at"] = workflow_run.started_at
    if workflow_run.finished_at is not None:
        payload["finished_at"] = workflow_run.finished_at
    return payload


def _serialize_node_records(
    node_records: tuple[object, ...],
    *,
    retain_node_records_enabled: bool = True,
) -> tuple[dict[str, object], ...]:
    """把节点执行记录转换为稳定 JSON 结构。"""

    if not retain_node_records_enabled:
        return ()

    serialized: list[dict[str, object]] = []
    for item in node_records:
        serialized.append(serialize_node_execution_record(item))
    return tuple(serialized)


def _merge_timing_metadata(existing_value: object, timing_payload: dict[str, object]) -> dict[str, object]:
    """合并 WorkflowRun 已有计时信息和本次 worker 返回计时。"""

    merged = dict(existing_value) if isinstance(existing_value, dict) else {}
    for key, value in timing_payload.items():
        if isinstance(value, bool):
            merged[str(key)] = value
            continue
        if isinstance(value, int | float | str) or value is None:
            merged[str(key)] = value
    return merged


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


def _iter_input_buffer_refs(value: object) -> Iterator[BufferRef]:
    """递归读取输入载荷里的 BufferRef。"""

    if isinstance(value, BufferRef):
        yield value
        return
    if isinstance(value, dict):
        buffer_ref_payload = value.get("buffer_ref")
        if isinstance(buffer_ref_payload, dict):
            try:
                yield BufferRef.model_validate(buffer_ref_payload)
            except Exception:
                pass
        for child_value in value.values():
            yield from _iter_input_buffer_refs(child_value)
        return
    if isinstance(value, list | tuple):
        for child_value in value:
            yield from _iter_input_buffer_refs(child_value)


def _now_isoformat() -> str:
    """返回当前 UTC 时间的 ISO8601 文本。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
