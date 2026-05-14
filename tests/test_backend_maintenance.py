"""backend-maintenance 命令测试。"""

from __future__ import annotations

from pathlib import Path

from backend.maintenance.main import cleanup_expired_preview_runs
from backend.service.domain.workflows.workflow_runtime_records import WorkflowPreviewRun
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.settings import (
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceSettings,
)
from tests.api_test_support import create_test_runtime


def test_cleanup_expired_preview_runs_removes_expired_records_and_snapshot_dirs(
    tmp_path: Path,
) -> None:
    """验证 maintenance 清理命令会删除已过期 preview run 及其 snapshot 目录。"""

    session_factory, dataset_storage, _ = create_test_runtime(
        tmp_path,
        database_name="backend-maintenance-preview-cleanup.db",
    )
    service_settings = BackendServiceSettings(
        database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
        dataset_storage=BackendServiceDatasetStorageConfig(
            root_dir=str(dataset_storage.root_dir)
        ),
    )
    _save_preview_run(
        session_factory,
        preview_run_id="preview-expired",
        retention_until="2026-05-14T09:59:59Z",
    )
    _save_preview_run(
        session_factory,
        preview_run_id="preview-active",
        retention_until="2026-05-14T10:00:01Z",
    )
    dataset_storage.write_json(
        "workflows/runtime/preview-runs/preview-expired/application.snapshot.json",
        {"application_id": "preview-expired"},
    )
    dataset_storage.write_json(
        "workflows/runtime/preview-runs/preview-active/application.snapshot.json",
        {"application_id": "preview-active"},
    )

    try:
        payload = cleanup_expired_preview_runs(
            backend_service_settings=service_settings,
            now_iso="2026-05-14T10:00:00Z",
        )
    finally:
        session_factory.engine.dispose()

    assert payload["command"] == "cleanup-preview-runs"
    assert payload["expired_count"] == 1
    assert payload["deleted_preview_run_ids"] == ["preview-expired"]
    assert payload["deleted_snapshot_dirs"] == [
        "workflows/runtime/preview-runs/preview-expired"
    ]
    assert not dataset_storage.resolve(
        "workflows/runtime/preview-runs/preview-expired"
    ).exists()
    assert dataset_storage.resolve(
        "workflows/runtime/preview-runs/preview-active/application.snapshot.json"
    ).is_file()
    remaining_preview_run_ids = _list_preview_run_ids(session_factory)
    assert remaining_preview_run_ids == ["preview-active"]


def _save_preview_run(
    session_factory,
    *,
    preview_run_id: str,
    retention_until: str,
) -> None:
    """写入测试使用的 preview run 记录。"""

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.workflow_runtime.save_preview_run(
            WorkflowPreviewRun(
                preview_run_id=preview_run_id,
                project_id="project-1",
                application_id="process-echo-app",
                source_kind="editor-preview",
                application_snapshot_object_key=(
                    f"workflows/runtime/preview-runs/{preview_run_id}/application.snapshot.json"
                ),
                template_snapshot_object_key=(
                    f"workflows/runtime/preview-runs/{preview_run_id}/template.snapshot.json"
                ),
                state="succeeded",
                created_at="2026-05-14T09:00:00Z",
                finished_at="2026-05-14T09:00:02Z",
                created_by="user-1",
                retention_until=retention_until,
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()


def _list_preview_run_ids(session_factory) -> list[str]:
    """读取当前测试数据库中的 preview run id 列表。"""

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        preview_runs = unit_of_work.workflow_runtime.list_preview_runs("project-1")
        return [item.preview_run_id for item in preview_runs]
    finally:
        unit_of_work.close()