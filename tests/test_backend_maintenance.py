"""backend-maintenance 命令测试。"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from backend.maintenance.main import cleanup_runtime_storage
from backend.service.application.auth.default_local_auth_seeder import DEFAULT_LOCAL_AUTH_USERNAME
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime, WorkflowRun
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import (
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceSettings,
)
from tests.api_test_support import create_test_runtime






def test_cleanup_runtime_storage_removes_short_lived_runtime_objects_but_keeps_project_assets(
    tmp_path: Path,
) -> None:
    """验证 runtime cleanup 会删除短期运行目录，但不会误删 Project 资产和存活 runtime。"""

    session_factory, dataset_storage, _ = create_test_runtime(
        tmp_path,
        database_name="backend-maintenance-runtime-storage-cleanup.db",
    )
    service_settings = BackendServiceSettings(
        database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
        dataset_storage=BackendServiceDatasetStorageConfig(
            root_dir=str(dataset_storage.root_dir)
        ),
    )
    _save_workflow_app_runtime(
        session_factory,
        workflow_runtime_id="workflow-runtime-keep",
    )
    _save_workflow_run(
        session_factory,
        workflow_run_id="workflow-run-expired",
        state="succeeded",
        created_at="2026-05-13T08:00:00Z",
        finished_at="2026-05-13T08:10:00Z",
    )
    _save_workflow_run(
        session_factory,
        workflow_run_id="workflow-run-active",
        state="running",
        created_at="2026-05-13T08:20:00Z",
        finished_at=None,
    )

    dataset_storage.write_text("projects/project-1/results/keep.txt", "keep")
    dataset_storage.write_text("runtime/inputs/inference/request-expired/input.png", "old")
    dataset_storage.write_text("runtime/inputs/inference/request-active/input.png", "new")
    dataset_storage.write_json(
        "workflows/runtime/app-runtimes/workflow-runtime-keep/application.snapshot.json",
        {"application_id": "keep"},
    )
    dataset_storage.write_json(
        "workflows/runtime/app-runtimes/workflow-runtime-orphan/application.snapshot.json",
        {"application_id": "orphan"},
    )
    dataset_storage.write_bytes("workflows/runtime/workflow-run-expired/events.jsonl", b"")
    dataset_storage.write_bytes("workflows/runtime/workflow-run-active/events.jsonl", b"")
    dataset_storage.write_bytes("workflows/runtime/workflow-run-orphan/events.jsonl", b"")

    _set_path_mtime(
        dataset_storage.resolve("runtime/inputs/inference/request-expired"),
        "2026-05-13T09:00:00Z",
    )
    _set_path_mtime(
        dataset_storage.resolve("runtime/inputs/inference/request-active"),
        "2026-05-15T11:30:00Z",
    )
    _set_path_mtime(
        dataset_storage.resolve("workflows/runtime/app-runtimes/workflow-runtime-keep"),
        "2026-05-13T09:30:00Z",
    )
    _set_path_mtime(
        dataset_storage.resolve("workflows/runtime/app-runtimes/workflow-runtime-orphan"),
        "2026-05-13T09:35:00Z",
    )
    _set_path_mtime(
        dataset_storage.resolve("workflows/runtime/workflow-run-orphan"),
        "2026-05-13T09:40:00Z",
    )

    try:
        payload = cleanup_runtime_storage(
            backend_service_settings=service_settings,
            now_iso="2026-05-15T10:00:00Z",
            retention_hours=24,
        )
    finally:
        session_factory.engine.dispose()

    assert payload["command"] == "cleanup-runtime-storage"
    assert payload["cutoff_time"] == "2026-05-14T10:00:00Z"
    assert payload["deleted_runtime_input_entries"] == [
        "runtime/inputs/inference/request-expired"
    ]
    assert payload["deleted_workflow_run_dirs"] == [
        "workflows/runtime/workflow-run-expired",
        "workflows/runtime/workflow-run-orphan",
    ]
    assert payload["deleted_orphan_app_runtime_dirs"] == [
        "workflows/runtime/app-runtimes/workflow-runtime-orphan"
    ]
    assert dataset_storage.resolve("projects/project-1/results/keep.txt").is_file()
    assert not dataset_storage.resolve("runtime/inputs/inference/request-expired").exists()
    assert dataset_storage.resolve("runtime/inputs/inference/request-active/input.png").is_file()
    assert dataset_storage.resolve(
        "workflows/runtime/app-runtimes/workflow-runtime-keep/application.snapshot.json"
    ).is_file()
    assert not dataset_storage.resolve(
        "workflows/runtime/app-runtimes/workflow-runtime-orphan"
    ).exists()
    assert not dataset_storage.resolve("workflows/runtime/workflow-run-expired").exists()
    assert dataset_storage.resolve("workflows/runtime/workflow-run-active/events.jsonl").is_file()
    assert not dataset_storage.resolve("workflows/runtime/workflow-run-orphan").exists()




def _save_workflow_app_runtime(
    session_factory,
    *,
    workflow_runtime_id: str,
) -> None:
    """写入测试使用的 WorkflowAppRuntime 记录。"""

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.workflow_runtime.save_workflow_app_runtime(
            WorkflowAppRuntime(
                workflow_runtime_id=workflow_runtime_id,
                project_id="project-1",
                application_id="process-echo-app",
                display_name="Process Echo App",
                application_snapshot_object_key=(
                    f"workflows/runtime/app-runtimes/{workflow_runtime_id}/application.snapshot.json"
                ),
                template_snapshot_object_key=(
                    f"workflows/runtime/app-runtimes/{workflow_runtime_id}/template.snapshot.json"
                ),
                created_at="2026-05-13T09:00:00Z",
                updated_at="2026-05-13T09:00:00Z",
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()


def _save_workflow_run(
    session_factory,
    *,
    workflow_run_id: str,
    state: str,
    created_at: str,
    finished_at: str | None,
) -> None:
    """写入测试使用的 WorkflowRun 记录。"""

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.workflow_runtime.save_workflow_run(
            WorkflowRun(
                workflow_run_id=workflow_run_id,
                workflow_runtime_id="workflow-runtime-keep",
                project_id="project-1",
                application_id="process-echo-app",
                state=state,
                created_at=created_at,
                finished_at=finished_at,
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()




def _set_path_mtime(path: Path, iso_time: str) -> None:
    """把测试路径的 mtime 调整到指定 UTC 时间。"""

    timestamp = datetime.fromisoformat(iso_time.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    os.utime(path, (timestamp, timestamp))
