"""deployment 进程事件的持久化与实时消息辅助。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from backend.service.application.events import ServiceEvent


@dataclass(frozen=True)
class YoloXDeploymentProcessEvent:
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
    """返回指定 deployment 事件文件的相对 object key。"""

    normalized_deployment_instance_id = deployment_instance_id.strip()
    return f"models/yolox/deployment-instances/{normalized_deployment_instance_id}/events.json"


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
) -> tuple[YoloXDeploymentProcessEvent, ...]:
    """从本地 object store 读取 deployment 事件列表。

    参数：
    - dataset_storage_root_dir：本地文件存储根目录。
    - deployment_instance_id：目标 DeploymentInstance id。
    - after_sequence：可选事件下界；只返回 sequence 更大的事件。
    - runtime_mode：可选运行通道过滤；支持 sync 或 async。
    - limit：可选返回条数上限；为空时返回全部命中的事件。

    返回：
    - tuple[YoloXDeploymentProcessEvent, ...]：按 sequence 升序排列的事件列表。
    """

    if after_sequence is not None and after_sequence < 0:
        return ()
    if limit is not None and limit <= 0:
        return ()

    events_path = _resolve_deployment_events_path(
        dataset_storage_root_dir=dataset_storage_root_dir,
        deployment_instance_id=deployment_instance_id,
    )
    if not events_path.exists():
        return ()
    try:
        payload = json.loads(events_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()

    filtered_events: list[YoloXDeploymentProcessEvent] = []
    normalized_runtime_mode = runtime_mode.strip() if isinstance(runtime_mode, str) else None
    for item in payload:
        if not isinstance(item, dict):
            continue
        sequence = item.get("sequence")
        created_at = item.get("created_at")
        event_type = item.get("event_type")
        message = item.get("message")
        item_runtime_mode = item.get("runtime_mode")
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
            or not isinstance(item_runtime_mode, str)
            or not item_runtime_mode
        ):
            continue
        if after_sequence is not None and sequence <= after_sequence:
            continue
        if normalized_runtime_mode is not None and item_runtime_mode != normalized_runtime_mode:
            continue
        payload_value = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        filtered_events.append(
            YoloXDeploymentProcessEvent(
                deployment_instance_id=deployment_instance_id,
                runtime_mode=item_runtime_mode,
                sequence=sequence,
                event_type=event_type,
                created_at=created_at,
                message=message,
                payload=dict(payload_value),
            )
        )
    filtered_tuple = tuple(filtered_events)
    if limit is None:
        return filtered_tuple
    return filtered_tuple[:limit]


def write_deployment_process_events(
    *,
    dataset_storage_root_dir: str,
    deployment_instance_id: str,
    events: tuple[YoloXDeploymentProcessEvent, ...],
) -> None:
    """把 deployment 事件列表写回本地 object store。"""

    events_path = _resolve_deployment_events_path(
        dataset_storage_root_dir=dataset_storage_root_dir,
        deployment_instance_id=deployment_instance_id,
    )
    events_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "deployment_instance_id": item.deployment_instance_id,
            "runtime_mode": item.runtime_mode,
            "sequence": item.sequence,
            "event_type": item.event_type,
            "created_at": item.created_at,
            "message": item.message,
            "payload": dict(item.payload),
        }
        for item in events
    ]
    events_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_deployment_process_service_event(
    event: YoloXDeploymentProcessEvent,
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


def _resolve_deployment_events_path(
    *,
    dataset_storage_root_dir: str,
    deployment_instance_id: str,
) -> Path:
    """把 deployment 事件 object key 解析到本地文件路径。"""

    object_key = build_deployment_events_object_key(deployment_instance_id)
    relative_path = Path(*object_key.split("/"))
    return Path(dataset_storage_root_dir) / relative_path