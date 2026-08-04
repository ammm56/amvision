"""Deployment 追加式事件日志测试。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.service.application.runtime.deployment.deployment_events import (
    append_deployment_process_event,
    build_deployment_events_object_key,
    read_deployment_process_events,
)


def _append_event(
    root_dir: Path,
    deployment_instance_id: str,
    event_index: int,
    *,
    runtime_mode: str = "sync",
) -> int:
    """追加一条测试事件并返回分配到的 sequence。"""

    event = append_deployment_process_event(
        dataset_storage_root_dir=str(root_dir),
        deployment_instance_id=deployment_instance_id,
        runtime_mode=runtime_mode,
        event_type="runtime.health",
        created_at=f"2026-08-04T00:00:{event_index:02d}Z",
        message=f"event-{event_index}",
        payload={"event_index": event_index},
    )
    return event.sequence


def test_deployment_events_use_generic_append_only_storage(tmp_path: Path) -> None:
    """验证 deployment 事件脱离模型目录并按 JSON Lines 追加。"""

    deployment_instance_id = "deployment-instance-append"
    object_key = build_deployment_events_object_key(deployment_instance_id)

    first_sequence = _append_event(tmp_path, deployment_instance_id, 1)
    event_path = tmp_path.joinpath(*object_key.split("/"))
    first_bytes = event_path.read_bytes()
    second_sequence = _append_event(
        tmp_path,
        deployment_instance_id,
        2,
        runtime_mode="async",
    )

    assert object_key == (
        "deployments/instances/deployment-instance-append/events.jsonl"
    )
    assert first_sequence == 1
    assert second_sequence == 2
    assert event_path.read_bytes().startswith(first_bytes)
    lines = event_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["sequence"] for line in lines] == [1, 2]

    filtered_events = read_deployment_process_events(
        dataset_storage_root_dir=str(tmp_path),
        deployment_instance_id=deployment_instance_id,
        after_sequence=1,
        runtime_mode="async",
        limit=1,
    )
    assert [event.sequence for event in filtered_events] == [2]
    assert filtered_events[0].payload == {"event_index": 2}


def test_deployment_event_append_recovers_from_truncated_tail(tmp_path: Path) -> None:
    """验证进程中断留下的半行不会破坏序号恢复和后续事件。"""

    deployment_instance_id = "deployment-instance-truncated"
    _append_event(tmp_path, deployment_instance_id, 1)
    event_path = tmp_path.joinpath(
        *build_deployment_events_object_key(deployment_instance_id).split("/")
    )
    with event_path.open("ab") as event_stream:
        event_stream.write(b'{"sequence":999')

    recovered_sequence = _append_event(tmp_path, deployment_instance_id, 2)
    events = read_deployment_process_events(
        dataset_storage_root_dir=str(tmp_path),
        deployment_instance_id=deployment_instance_id,
    )

    assert recovered_sequence == 2
    assert [event.sequence for event in events] == [1, 2]
    assert [event.message for event in events] == ["event-1", "event-2"]


def test_deployment_event_append_serializes_concurrent_writers(tmp_path: Path) -> None:
    """验证同一服务进程内并发追加不会产生重复或断裂 sequence。"""

    deployment_instance_id = "deployment-instance-concurrent"
    event_count = 24
    with ThreadPoolExecutor(max_workers=8) as executor:
        sequences = tuple(
            executor.map(
                lambda index: _append_event(
                    tmp_path,
                    deployment_instance_id,
                    index,
                ),
                range(event_count),
            )
        )

    events = read_deployment_process_events(
        dataset_storage_root_dir=str(tmp_path),
        deployment_instance_id=deployment_instance_id,
    )

    assert sorted(sequences) == list(range(1, event_count + 1))
    assert [event.sequence for event in events] == list(range(1, event_count + 1))
    assert len({event.payload["event_index"] for event in events}) == event_count
