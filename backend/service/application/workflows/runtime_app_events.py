"""WorkflowAppRuntime 事件存储与实时分发辅助。"""

from __future__ import annotations

from threading import Lock

from backend.contracts.workflows.resource_semantics import build_workflow_app_runtime_events_object_key
from backend.service.application.events import InMemoryServiceEventBus, ServiceEvent
from backend.service.application.project_summary import (
    PROJECT_SUMMARY_TOPIC_WORKFLOW_APP_RUNTIMES,
    publish_project_summary_event,
    should_publish_project_summary_for_runtime_event,
)
from backend.service.application.workflows.runtime_payload_sanitizer import sanitize_runtime_mapping
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowAppRuntimeEvent,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


MAX_PERSISTED_WORKFLOW_RUNTIME_HEARTBEATS = 256

_EVENT_LOCK = Lock()
_WORKFLOW_APP_RUNTIME_EVENT_LOCKS: dict[str, Lock] = {}


def resolve_workflow_app_runtime_event_lock(workflow_runtime_id: str) -> Lock:
    """返回指定 WorkflowAppRuntime 事件文件的写锁。"""

    normalized_workflow_runtime_id = workflow_runtime_id.strip()
    with _EVENT_LOCK:
        event_lock = _WORKFLOW_APP_RUNTIME_EVENT_LOCKS.get(normalized_workflow_runtime_id)
        if event_lock is None:
            event_lock = Lock()
            _WORKFLOW_APP_RUNTIME_EVENT_LOCKS[normalized_workflow_runtime_id] = event_lock
        return event_lock


def read_workflow_app_runtime_events(
    dataset_storage: LocalDatasetStorage,
    workflow_runtime_id: str,
    *,
    after_sequence: int | None = None,
    limit: int | None = None,
) -> tuple[WorkflowAppRuntimeEvent, ...]:
    """读取一条 WorkflowAppRuntime 的事件列表。

    参数：
    - dataset_storage：本地文件存储。
    - workflow_runtime_id：目标 WorkflowAppRuntime id。
    - after_sequence：可选事件下界；只返回 sequence 更大的事件。
    - limit：可选返回条数上限；为空时返回全部命中的事件。

    返回：
    - tuple[WorkflowAppRuntimeEvent, ...]：按 sequence 升序排列的事件列表。
    """

    if after_sequence is not None and after_sequence < 0:
        return ()
    if limit is not None and limit <= 0:
        return ()

    object_key = build_workflow_app_runtime_events_object_key(workflow_runtime_id)
    if not dataset_storage.resolve(object_key).exists():
        return ()
    payload = dataset_storage.read_json(object_key)
    if not isinstance(payload, list):
        return ()
    events: list[WorkflowAppRuntimeEvent] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        sequence = item.get("sequence")
        created_at = item.get("created_at")
        event_type = item.get("event_type")
        message = item.get("message")
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
        ):
            continue
        payload_value = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        events.append(
            WorkflowAppRuntimeEvent(
                workflow_runtime_id=workflow_runtime_id,
                sequence=sequence,
                event_type=event_type,
                created_at=created_at,
                message=message,
                payload=dict(payload_value),
            )
        )
    filtered_events: tuple[WorkflowAppRuntimeEvent, ...] = tuple(events)
    if after_sequence is not None:
        filtered_events = tuple(item for item in filtered_events if item.sequence > after_sequence)
    if limit is None:
        return filtered_events
    return filtered_events[:limit]


def write_workflow_app_runtime_events(
    dataset_storage: LocalDatasetStorage,
    workflow_runtime_id: str,
    events: tuple[WorkflowAppRuntimeEvent, ...],
) -> None:
    """把 WorkflowAppRuntime 事件列表写回 events.json。"""

    payload = [
        {
            "workflow_runtime_id": item.workflow_runtime_id,
            "sequence": item.sequence,
            "event_type": item.event_type,
            "created_at": item.created_at,
            "message": item.message,
            "payload": sanitize_runtime_mapping(item.payload),
        }
        for item in events
    ]
    dataset_storage.write_json(build_workflow_app_runtime_events_object_key(workflow_runtime_id), payload)


def append_workflow_app_runtime_event(
    *,
    dataset_storage: LocalDatasetStorage,
    service_event_bus: InMemoryServiceEventBus | None,
    session_factory: SessionFactory | None,
    workflow_app_runtime: WorkflowAppRuntime,
    event_type: str,
    message: str,
    payload: dict[str, object] | None = None,
) -> WorkflowAppRuntimeEvent:
    """向 WorkflowAppRuntime 的 events.json 追加一条事件并发布到事件总线。"""

    event_lock = resolve_workflow_app_runtime_event_lock(workflow_app_runtime.workflow_runtime_id)
    with event_lock:
        existing_events = list(
            read_workflow_app_runtime_events(
                dataset_storage,
                workflow_app_runtime.workflow_runtime_id,
            )
        )
        next_sequence = max((item.sequence for item in existing_events), default=0) + 1
        event = WorkflowAppRuntimeEvent(
            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
            sequence=next_sequence,
            event_type=event_type.strip() or "runtime.updated",
            created_at=workflow_app_runtime.updated_at,
            message=message.strip() or "workflow app runtime 事件",
            payload=sanitize_runtime_mapping(
                {
                    **build_workflow_app_runtime_event_payload(workflow_app_runtime),
                    **dict(payload or {}),
                }
            ),
        )
        existing_events.append(event)
        compacted_events = _compact_workflow_app_runtime_events(existing_events)
        write_workflow_app_runtime_events(
            dataset_storage,
            workflow_app_runtime.workflow_runtime_id,
            tuple(compacted_events),
        )
    if service_event_bus is not None:
        service_event_bus.publish(build_workflow_app_runtime_service_event(event))
    if session_factory is not None and should_publish_project_summary_for_runtime_event(event.event_type):
        publish_project_summary_event(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            service_event_bus=service_event_bus,
            project_id=workflow_app_runtime.project_id,
            topic=PROJECT_SUMMARY_TOPIC_WORKFLOW_APP_RUNTIMES,
            source_stream="workflows.app-runtimes.events",
            source_resource_kind="workflow_app_runtime",
            source_resource_id=workflow_app_runtime.workflow_runtime_id,
        )
    return event


def build_workflow_app_runtime_event_payload(
    workflow_app_runtime: WorkflowAppRuntime,
) -> dict[str, object]:
    """构造 WorkflowAppRuntime 事件的基础 payload。"""

    payload: dict[str, object] = {
        "desired_state": workflow_app_runtime.desired_state,
        "observed_state": workflow_app_runtime.observed_state,
        "request_timeout_seconds": workflow_app_runtime.request_timeout_seconds,
        "heartbeat_interval_seconds": workflow_app_runtime.heartbeat_interval_seconds,
        "heartbeat_timeout_seconds": workflow_app_runtime.heartbeat_timeout_seconds,
        "health_summary": dict(workflow_app_runtime.health_summary),
    }
    if workflow_app_runtime.last_error is not None:
        payload["last_error"] = workflow_app_runtime.last_error
    if workflow_app_runtime.heartbeat_at is not None:
        payload["heartbeat_at"] = workflow_app_runtime.heartbeat_at
    if workflow_app_runtime.last_started_at is not None:
        payload["last_started_at"] = workflow_app_runtime.last_started_at
    if workflow_app_runtime.last_stopped_at is not None:
        payload["last_stopped_at"] = workflow_app_runtime.last_stopped_at
    if workflow_app_runtime.worker_process_id is not None:
        payload["worker_process_id"] = workflow_app_runtime.worker_process_id
    if workflow_app_runtime.loaded_snapshot_fingerprint is not None:
        payload["loaded_snapshot_fingerprint"] = workflow_app_runtime.loaded_snapshot_fingerprint
    return payload


def build_workflow_app_runtime_service_event(event: WorkflowAppRuntimeEvent) -> ServiceEvent:
    """把 WorkflowAppRuntime 事件转换为 ServiceEvent。"""

    return ServiceEvent(
        stream="workflows.app-runtimes.events",
        resource_kind="workflow_app_runtime",
        resource_id=event.workflow_runtime_id,
        event_type=event.event_type,
        occurred_at=event.created_at,
        cursor=str(event.sequence),
        payload={
            "workflow_runtime_id": event.workflow_runtime_id,
            "sequence": event.sequence,
            "message": event.message,
            **dict(event.payload),
        },
    )


def _compact_workflow_app_runtime_events(
    events: list[WorkflowAppRuntimeEvent],
) -> list[WorkflowAppRuntimeEvent]:
    """裁剪过多的 heartbeat 事件，避免长期运行文件无限增长。"""

    heartbeat_events = [item for item in events if item.event_type == "runtime.heartbeat"]
    if len(heartbeat_events) <= MAX_PERSISTED_WORKFLOW_RUNTIME_HEARTBEATS:
        return events
    heartbeat_sequences_to_keep = {
        item.sequence
        for item in heartbeat_events[-MAX_PERSISTED_WORKFLOW_RUNTIME_HEARTBEATS:]
    }
    compacted_events: list[WorkflowAppRuntimeEvent] = []
    for item in events:
        if item.event_type == "runtime.heartbeat" and item.sequence not in heartbeat_sequences_to_keep:
            continue
        compacted_events.append(item)
    return compacted_events