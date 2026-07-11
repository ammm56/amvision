"""WorkflowAppRuntime 事件日志测试。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.workflows.resource_semantics import (
    build_workflow_app_runtime_events_object_key,
)
from backend.service.application.workflows.runtime_app_events import (
    append_workflow_app_runtime_event,
    read_workflow_app_runtime_events,
)
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_read_workflow_app_runtime_events_ignores_corrupt_event_file(
    tmp_path: Path,
) -> None:
    """验证损坏的 runtime events.json 不会阻塞事件读取。"""

    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    workflow_runtime_id = "workflow-runtime-corrupt-events"
    object_key = build_workflow_app_runtime_events_object_key(workflow_runtime_id)
    event_path = dataset_storage.resolve(object_key)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.write_bytes(b"\x00" * 128)

    events = read_workflow_app_runtime_events(dataset_storage, workflow_runtime_id)

    assert events == ()


def test_append_workflow_app_runtime_event_recovers_corrupt_event_file(
    tmp_path: Path,
) -> None:
    """验证追加事件会用新的有效事件列表覆盖损坏的 events.json。"""

    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    workflow_runtime_id = "workflow-runtime-recover-events"
    object_key = build_workflow_app_runtime_events_object_key(workflow_runtime_id)
    event_path = dataset_storage.resolve(object_key)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.write_bytes(b"\x00" * 128)

    event = append_workflow_app_runtime_event(
        dataset_storage=dataset_storage,
        service_event_bus=None,
        session_factory=None,
        workflow_app_runtime=WorkflowAppRuntime(
            workflow_runtime_id=workflow_runtime_id,
            project_id="project-1",
            application_id="workflow-app-test",
            display_name="Test Runtime",
            application_snapshot_object_key=(
                f"workflows/runtime/app-runtimes/{workflow_runtime_id}/application.snapshot.json"
            ),
            template_snapshot_object_key=(
                f"workflows/runtime/app-runtimes/{workflow_runtime_id}/template.snapshot.json"
            ),
            created_at="2026-07-11T10:00:00Z",
            updated_at="2026-07-11T10:00:00Z",
        ),
        event_type="runtime.deleted",
        message="workflow app runtime 已删除",
    )

    payload = json.loads(event_path.read_text(encoding="utf-8"))
    assert event.sequence == 1
    assert payload[0]["event_type"] == "runtime.deleted"
    assert payload[0]["sequence"] == 1
