"""WorkflowRun 持久化辅助。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timezone
from threading import Lock

from backend.contracts.buffers import BufferRef
from backend.contracts.workflows.resource_semantics import build_workflow_run_events_object_key
from backend.service.application.errors import ServiceConfigurationError
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
        pool_name_value = buffer_ref.metadata.get("pool_name")
        register_local_buffer_lease_cleanup(
            payload,
            lease_id=buffer_ref.lease_id,
            pool_name=pool_name_value if isinstance(pool_name_value, str) else None,
        )
    return payload


def append_workflow_run_event(
    *,
    dataset_storage: LocalDatasetStorage,
    workflow_run: WorkflowRun,
    event_lock: Lock,
    event_type: str,
    message: str,
    payload: dict[str, object] | None = None,
) -> WorkflowRunEvent:
    """按 WorkflowRun 保留策略追加事件到 events.json。"""

    event_payload = sanitize_runtime_mapping(
        {
            **build_workflow_run_event_payload(workflow_run),
            **dict(payload or {}),
        }
    )
    if not should_retain_workflow_run_trace(workflow_run):
        return WorkflowRunEvent(
            workflow_run_id=workflow_run.workflow_run_id,
            workflow_runtime_id=workflow_run.workflow_runtime_id,
            sequence=0,
            event_type=event_type.strip() or "run.updated",
            created_at=_now_isoformat(),
            message=message.strip() or "workflow run 事件",
            payload=event_payload,
        )

    with event_lock:
        existing_events = list(
            read_workflow_run_events(dataset_storage, workflow_run.workflow_run_id)
        )
        event = WorkflowRunEvent(
            workflow_run_id=workflow_run.workflow_run_id,
            workflow_runtime_id=workflow_run.workflow_runtime_id,
            sequence=len(existing_events) + 1,
            event_type=event_type.strip() or "run.updated",
            created_at=_now_isoformat(),
            message=message.strip() or "workflow run 事件",
            payload=event_payload,
        )
        existing_events.append(event)
        write_workflow_run_events(
            dataset_storage,
            workflow_run.workflow_run_id,
            tuple(existing_events),
        )
    return event


def read_workflow_run_events(
    dataset_storage: LocalDatasetStorage,
    workflow_run_id: str,
) -> tuple[WorkflowRunEvent, ...]:
    """读取一条 WorkflowRun 的全部事件。"""

    object_key = build_workflow_run_events_object_key(workflow_run_id)
    if not dataset_storage.resolve(object_key).exists():
        return ()
    payload = dataset_storage.read_json(object_key)
    if not isinstance(payload, list):
        raise ServiceConfigurationError(
            "workflow run 事件文件格式无效",
            details={"workflow_run_id": workflow_run_id},
        )
    events: list[WorkflowRunEvent] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        sequence = item.get("sequence")
        created_at = item.get("created_at")
        event_type = item.get("event_type")
        message = item.get("message")
        workflow_runtime_id = item.get("workflow_runtime_id")
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
            continue
        payload_value = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        events.append(
            WorkflowRunEvent(
                workflow_run_id=workflow_run_id,
                workflow_runtime_id=workflow_runtime_id,
                sequence=sequence,
                event_type=event_type,
                created_at=created_at,
                message=message,
                payload=payload_value,
            )
        )
    return tuple(events)


def write_workflow_run_events(
    dataset_storage: LocalDatasetStorage,
    workflow_run_id: str,
    events: tuple[WorkflowRunEvent, ...],
) -> None:
    """把 WorkflowRun 事件列表写回 events.json。"""

    payload = [
        {
            "workflow_run_id": item.workflow_run_id,
            "workflow_runtime_id": item.workflow_runtime_id,
            "sequence": item.sequence,
            "event_type": item.event_type,
            "created_at": item.created_at,
            "message": item.message,
            "payload": sanitize_runtime_mapping(item.payload),
        }
        for item in events
    ]
    dataset_storage.write_json(build_workflow_run_events_object_key(workflow_run_id), payload)


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
