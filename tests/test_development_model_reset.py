"""开发阶段模型状态重置测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select

from backend.maintenance.development_model_reset import (
    DevelopmentModelResetRequest,
    reset_development_model_state,
)
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
)
from backend.service.infrastructure.persistence.model_orm import ModelRecord
from backend.service.infrastructure.persistence.task_orm import TaskRecordEntity
from backend.service.infrastructure.persistence.workflow_runtime_orm import (
    WorkflowAppRuntimeRecord,
    WorkflowPreviewRunRecord,
    WorkflowRunRecord,
)
from backend.service.infrastructure.persistence.workflow_trigger_source_orm import (
    WorkflowTriggerSourceRecord,
)


def test_reset_development_model_state_preserves_dataset_state(tmp_path: Path) -> None:
    """重置只删除模型派生状态，并保留数据集文件、任务和队列。"""

    database_path = tmp_path / "database" / "amvision.db"
    storage_root = tmp_path / "files"
    queue_root = tmp_path / "queue"
    buffer_root = tmp_path / "buffers"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    settings = SimpleNamespace(
        queue=SimpleNamespace(root_dir=str(queue_root)),
        local_buffer_broker=SimpleNamespace(root_dir=str(buffer_root)),
        to_database_settings=lambda: DatabaseSettings(
            url=f"sqlite+pysqlite:///{database_path.as_posix()}"
        ),
        to_dataset_storage_settings=lambda: DatasetStorageSettings(
            root_dir=str(storage_root)
        ),
    )
    session_factory = SessionFactory(settings.to_database_settings())
    initialize_database_schema(session_factory)
    with session_factory.create_session() as session:
        session.add_all(
            (
                TaskRecordEntity(
                    task_id="dataset-import-1",
                    task_kind="dataset-import",
                    display_name="dataset",
                    project_id="project-1",
                    created_at="2026-07-26T00:00:00Z",
                    state="succeeded",
                ),
                TaskRecordEntity(
                    task_id="training-1",
                    task_kind="yolo11-training",
                    display_name="training",
                    project_id="project-1",
                    created_at="2026-07-26T00:00:00Z",
                    state="succeeded",
                ),
                ModelRecord(
                    model_id="model-1",
                    project_id="project-1",
                    scope_kind="project",
                    model_name="trained",
                    model_type="yolo11",
                    task_type="detection",
                    model_scale="s",
                ),
                WorkflowAppRuntimeRecord(
                    workflow_runtime_id="runtime-1",
                    project_id="project-1",
                    application_id="application-1",
                    application_snapshot_object_key="workflows/runtime/app.json",
                    template_snapshot_object_key="workflows/runtime/template.json",
                    desired_state="stopped",
                    observed_state="stopped",
                    created_at="2026-07-26T00:00:00Z",
                    updated_at="2026-07-26T00:00:00Z",
                ),
                WorkflowRunRecord(
                    workflow_run_id="run-1",
                    workflow_runtime_id="runtime-1",
                    project_id="project-1",
                    application_id="application-1",
                    state="succeeded",
                    created_at="2026-07-26T00:00:00Z",
                ),
                WorkflowPreviewRunRecord(
                    preview_run_id="preview-1",
                    project_id="project-1",
                    application_id="application-1",
                    source_kind="application",
                    application_snapshot_object_key="workflows/runtime/preview-app.json",
                    template_snapshot_object_key="workflows/runtime/preview-template.json",
                    state="succeeded",
                    created_at="2026-07-26T00:00:00Z",
                ),
                WorkflowTriggerSourceRecord(
                    trigger_source_id="trigger-1",
                    project_id="project-1",
                    trigger_kind="http",
                    workflow_runtime_id="runtime-1",
                    submit_mode="async",
                    desired_state="stopped",
                    observed_state="stopped",
                    created_at="2026-07-26T00:00:00Z",
                    updated_at="2026-07-26T00:00:00Z",
                ),
            )
        )
        session.commit()
    session_factory.engine.dispose()

    _write_marker(storage_root / "datasets" / "dataset-1" / "manifest.json")
    _write_marker(storage_root / "models" / "pretrained" / "keep.txt")
    _write_marker(storage_root / "task-runs" / "training-1" / "result.json")
    _write_marker(storage_root / "workflows" / "runtime" / "run-1" / "state.json")
    _write_marker(queue_root / "dataset-imports" / "dataset-import-1.json")
    _write_marker(queue_root / "yolo11-trainings" / "training-1.json")
    _write_marker(queue_root / "_worker_health" / "worker.json")
    _write_marker(tmp_path / "worker" / "worker-1.json")
    _write_marker(buffer_root / "buffer-1.bin")

    preview = reset_development_model_state(
        request=DevelopmentModelResetRequest(confirm=False),
        backend_service_settings=settings,
    )
    assert preview["confirmed"] is False
    assert preview["preview"]["models"] == 1
    assert preview["preview"]["model_task_count"] == 1

    result = reset_development_model_state(
        request=DevelopmentModelResetRequest(confirm=True),
        backend_service_settings=settings,
    )

    assert result["confirmed"] is True
    assert result["deleted_counts"]["models"] == 1
    assert result["deleted_counts"]["tasks"] == 1
    assert result["deleted_counts"]["workflow_app_runtimes"] == 1
    assert result["pending_cleanup"] == []
    assert (storage_root / "datasets" / "dataset-1" / "manifest.json").is_file()
    assert (storage_root / "models" / "pretrained" / "keep.txt").is_file()
    assert (queue_root / "dataset-imports" / "dataset-import-1.json").is_file()
    assert (queue_root / "_worker_health" / "worker.json").is_file()
    assert not (storage_root / "task-runs" / "training-1").exists()
    assert not (queue_root / "yolo11-trainings").exists()

    verification_factory = SessionFactory(settings.to_database_settings())
    with verification_factory.create_session() as session:
        task_kinds = tuple(session.scalars(select(TaskRecordEntity.task_kind)))
        assert task_kinds == ("dataset-import",)
        assert _count(session, ModelRecord) == 0
        assert _count(session, WorkflowAppRuntimeRecord) == 0
        assert _count(session, WorkflowRunRecord) == 0
        assert _count(session, WorkflowPreviewRunRecord) == 0
        assert _count(session, WorkflowTriggerSourceRecord) == 0
    verification_factory.engine.dispose()


def _write_marker(path: Path) -> None:
    """创建测试用派生文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("test", encoding="utf-8")


def _count(session: object, entity: type) -> int:
    """统计测试数据库记录数。"""

    return int(session.scalar(select(func.count()).select_from(entity)) or 0)
