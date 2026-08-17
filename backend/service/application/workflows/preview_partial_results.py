"""从 Workflow Preview 事件恢复已经完成的节点记录。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from backend.service.application.workflows.runtime_payload_sanitizer import (
    serialize_node_execution_record,
)


def build_completed_node_records_from_events(
    events: Iterable[object],
) -> tuple[dict[str, object], ...]:
    """把 ``node.completed`` 事件转换为稳定的 node_records。

    Preview 的最终状态可以是 failed 或 timed_out，但本次运行中已经成功
    完成的节点仍是有效调试结果。该函数只读取节点事件，不把输出复制到错误详情。
    """

    node_records: list[dict[str, object]] = []
    for event in events:
        event_type, payload = _read_event(event)
        if event_type != "node.completed" or payload is None:
            continue
        node_id = payload.get("node_id")
        if not isinstance(node_id, str) or not node_id.strip():
            continue
        node_records.append(
            serialize_node_execution_record(
                {
                    "node_id": node_id,
                    "node_type_id": payload.get("node_type_id"),
                    "runtime_kind": payload.get("runtime_kind"),
                    "duration_ms": payload.get("duration_ms"),
                    "inputs": payload.get("inputs"),
                    "outputs": payload.get("outputs"),
                }
            )
        )
    return tuple(node_records)


def _read_event(
    event: object,
) -> tuple[str, Mapping[str, object] | None]:
    """兼容事件 dataclass 与跨进程字典。"""

    if isinstance(event, Mapping):
        event_type = event.get("event_type")
        payload = event.get("payload")
    else:
        event_type = getattr(event, "event_type", None)
        payload = getattr(event, "payload", None)
    return (
        event_type if isinstance(event_type, str) else "",
        payload if isinstance(payload, Mapping) else None,
    )
