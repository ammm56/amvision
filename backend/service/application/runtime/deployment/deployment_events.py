"""deployment 进程事件的追加式持久化与实时消息辅助。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from backend.service.application.events import ServiceEvent


@dataclass(frozen=True)
class DeploymentProcessEvent:
    """描述一条 deployment 进程生命周期或健康事件。"""

    deployment_instance_id: str
    runtime_mode: str
    sequence: int
    event_type: str
    created_at: str
    message: str
    payload: dict[str, object] = field(default_factory=dict)


_EVENT_LOCK = Lock()
_EVENT_LOCKS: dict[str, Lock] = {}


def build_deployment_events_object_key(deployment_instance_id: str) -> str:
    """返回指定 deployment 追加式事件文件的相对 object key。"""

    normalized_deployment_instance_id = deployment_instance_id.strip()
    return (
        "deployments/instances/"
        f"{normalized_deployment_instance_id}/events.jsonl"
    )


def resolve_deployment_event_lock(deployment_instance_id: str) -> Lock:
    """返回指定 deployment 事件文件的进程内写锁。"""

    normalized_deployment_instance_id = deployment_instance_id.strip()
    with _EVENT_LOCK:
        lock = _EVENT_LOCKS.get(normalized_deployment_instance_id)
        if lock is None:
            lock = Lock()
            _EVENT_LOCKS[normalized_deployment_instance_id] = lock
        return lock


def read_deployment_process_events(
    *,
    dataset_storage_root_dir: str,
    deployment_instance_id: str,
    after_sequence: int | None = None,
    runtime_mode: str | None = None,
    limit: int | None = None,
) -> tuple[DeploymentProcessEvent, ...]:
    """从本地 object store 按追加顺序读取 deployment 事件。

    损坏或未写完整的单行会被跳过，不影响同一文件中的其他有效事件。
    """

    if after_sequence is not None and after_sequence < 0:
        return ()
    if limit is not None and limit <= 0:
        return ()

    events_path = _resolve_deployment_events_path(
        dataset_storage_root_dir=dataset_storage_root_dir,
        deployment_instance_id=deployment_instance_id,
    )
    if not events_path.is_file():
        return ()

    normalized_runtime_mode = runtime_mode.strip() if isinstance(runtime_mode, str) else None
    filtered_events: list[DeploymentProcessEvent] = []
    with events_path.open("r", encoding="utf-8", errors="replace") as event_stream:
        for line in event_stream:
            event = _parse_deployment_process_event_line(
                line,
                deployment_instance_id=deployment_instance_id,
            )
            if event is None:
                continue
            if after_sequence is not None and event.sequence <= after_sequence:
                continue
            if normalized_runtime_mode is not None and event.runtime_mode != normalized_runtime_mode:
                continue
            filtered_events.append(event)
            if limit is not None and len(filtered_events) >= limit:
                break
    return tuple(filtered_events)


def append_deployment_process_event(
    *,
    dataset_storage_root_dir: str,
    deployment_instance_id: str,
    runtime_mode: str,
    event_type: str,
    created_at: str,
    message: str,
    payload: dict[str, object] | None = None,
) -> DeploymentProcessEvent:
    """为指定 deployment 原子分配序号并追加一条 JSON Lines 事件。

    同一服务进程内的 sync、async supervisor 共用实例锁，因此序号分配和文件
    追加不会交叉。服务重启后从文件末尾最后一条有效事件恢复序号。
    """

    event_lock = resolve_deployment_event_lock(deployment_instance_id)
    with event_lock:
        events_path = _resolve_deployment_events_path(
            dataset_storage_root_dir=dataset_storage_root_dir,
            deployment_instance_id=deployment_instance_id,
        )
        sequence = _read_last_valid_event_sequence(
            events_path,
            deployment_instance_id=deployment_instance_id,
        ) + 1
        event = DeploymentProcessEvent(
            deployment_instance_id=deployment_instance_id,
            runtime_mode=runtime_mode,
            sequence=sequence,
            event_type=event_type,
            created_at=created_at,
            message=message,
            payload=dict(payload or {}),
        )
        events_path.parent.mkdir(parents=True, exist_ok=True)
        encoded_event = (
            json.dumps(
                _serialize_deployment_process_event(event),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        with events_path.open("ab+") as event_stream:
            event_stream.seek(0, 2)
            file_size = event_stream.tell()
            if file_size > 0:
                event_stream.seek(-1, 2)
                if event_stream.read(1) != b"\n":
                    event_stream.seek(0, 2)
                    event_stream.write(b"\n")
            event_stream.seek(0, 2)
            event_stream.write(encoded_event)
            event_stream.flush()
        return event


def build_deployment_process_service_event(
    event: DeploymentProcessEvent,
) -> ServiceEvent:
    """把 deployment 事件转换为统一 ServiceEvent。"""

    return ServiceEvent(
        stream="deployments.events",
        resource_kind="deployment_instance",
        resource_id=event.deployment_instance_id,
        event_type=event.event_type,
        occurred_at=event.created_at,
        cursor=str(event.sequence),
        payload={
            "deployment_instance_id": event.deployment_instance_id,
            "runtime_mode": event.runtime_mode,
            "sequence": event.sequence,
            "message": event.message,
            **dict(event.payload),
        },
    )


def _serialize_deployment_process_event(
    event: DeploymentProcessEvent,
) -> dict[str, object]:
    """把 deployment 事件转换为 JSON 可序列化对象。"""

    return {
        "deployment_instance_id": event.deployment_instance_id,
        "runtime_mode": event.runtime_mode,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "created_at": event.created_at,
        "message": event.message,
        "payload": dict(event.payload),
    }


def _parse_deployment_process_event_line(
    line: str,
    *,
    deployment_instance_id: str,
) -> DeploymentProcessEvent | None:
    """解析一行 deployment 事件；无效行返回 None。"""

    try:
        item = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(item, dict):
        return None
    sequence = item.get("sequence")
    created_at = item.get("created_at")
    event_type = item.get("event_type")
    message = item.get("message")
    runtime_mode = item.get("runtime_mode")
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
        or not isinstance(runtime_mode, str)
        or not runtime_mode
    ):
        return None
    payload_value = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return DeploymentProcessEvent(
        deployment_instance_id=deployment_instance_id,
        runtime_mode=runtime_mode,
        sequence=sequence,
        event_type=event_type,
        created_at=created_at,
        message=message,
        payload=dict(payload_value),
    )


def _read_last_valid_event_sequence(
    events_path: Path,
    *,
    deployment_instance_id: str,
) -> int:
    """从追加式事件文件末尾恢复最后一条有效 sequence。"""

    if not events_path.is_file():
        return 0
    with events_path.open("rb") as event_stream:
        event_stream.seek(0, 2)
        position = event_stream.tell()
        pending = bytearray()
        while position > 0:
            position -= 1
            event_stream.seek(position)
            byte = event_stream.read(1)
            if byte == b"\n":
                if pending:
                    event = _parse_deployment_process_event_line(
                        bytes(reversed(pending)).decode("utf-8", errors="replace"),
                        deployment_instance_id=deployment_instance_id,
                    )
                    if event is not None:
                        return event.sequence
                    pending.clear()
                continue
            pending.append(byte[0])
        if pending:
            event = _parse_deployment_process_event_line(
                bytes(reversed(pending)).decode("utf-8", errors="replace"),
                deployment_instance_id=deployment_instance_id,
            )
            if event is not None:
                return event.sequence
    return 0


def _resolve_deployment_events_path(
    *,
    dataset_storage_root_dir: str,
    deployment_instance_id: str,
) -> Path:
    """把 deployment 事件 object key 解析到本地文件路径。"""

    object_key = build_deployment_events_object_key(deployment_instance_id)
    relative_path = Path(*object_key.split("/"))
    return Path(dataset_storage_root_dir) / relative_path
