"""开发阶段 Workflow 全量重置测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from backend.maintenance import development_workflow_reset as reset_module
from backend.maintenance.development_workflow_reset import (
    DevelopmentWorkflowHistoryClearRequest,
    DevelopmentWorkflowResetRequest,
    clear_development_workflow_history,
    reset_development_workflow_state,
)
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
)
from backend.service.infrastructure.persistence.model_orm import ModelRecord
from backend.service.infrastructure.persistence.workflow_runtime_orm import (
    WorkflowApplicationLifecycleRecord,
    WorkflowAppRuntimeRecord,
    WorkflowAppVersionRecord,
    WorkflowExecutionPolicyRecord,
    WorkflowPreviewRunRecord,
    WorkflowRunRecord,
    WorkflowRuntimeRevisionRecord,
)
from backend.service.infrastructure.persistence.workflow_trigger_source_orm import (
    WorkflowTriggerSourceRecord,
)


def test_reset_development_workflow_state_clears_only_workflow_state(
    tmp_path: Path,
) -> None:
    """验证重置清除完整 Workflow 链路，但保留模型和其他共享内存数据。"""

    settings, storage_root, buffer_root = _build_settings(tmp_path)
    session_factory = SessionFactory(settings.to_database_settings())
    initialize_database_schema(session_factory)
    _seed_stopped_workflow_state(session_factory)
    session_factory.engine.dispose()

    _write_marker(storage_root / "workflows" / "projects" / "project-1" / "app.json")
    _write_marker(storage_root / "workflows" / "runtime" / "run-1" / "events.jsonl")
    _write_marker(storage_root / "projects" / "project-1" / "workflow" / "old.json")
    _write_marker(
        storage_root
        / "projects"
        / "project-1"
        / "inputs"
        / "workflow-applications"
        / "input.png"
    )
    _write_marker(
        storage_root
        / "projects"
        / "project-1"
        / "results"
        / "workflow-applications"
        / "result.json"
    )
    _write_marker(storage_root / "runtime" / "inputs" / "runtime-1" / "input.json")
    _write_marker(storage_root / "runtime" / "inputs" / "inference" / "keep.png")
    _write_marker(buffer_root / "local-message" / "workflow-trigger" / "mailbox.mmap")
    _write_marker(buffer_root / "local-message" / "inference" / "mailbox.mmap")
    _write_marker(buffer_root / "local-buffer" / "images.mmap")

    preview = reset_development_workflow_state(
        request=DevelopmentWorkflowResetRequest(confirm=False),
        backend_service_settings=settings,
    )
    assert preview["confirmed"] is False
    assert preview["preview"]["database_counts"] == {
        "workflow_trigger_sources": 1,
        "workflow_runs": 1,
        "workflow_app_runtimes": 1,
        "workflow_runtime_revisions": 1,
        "workflow_app_versions": 1,
        "workflow_application_lifecycles": 1,
        "workflow_preview_runs": 1,
        "workflow_execution_policies": 1,
    }
    assert all(value == 0 for value in preview["preview"]["active_resources"].values())
    assert (storage_root / "workflows" / "projects" / "project-1" / "app.json").is_file()

    result = reset_development_workflow_state(
        request=DevelopmentWorkflowResetRequest(confirm=True),
        backend_service_settings=settings,
    )

    assert result["confirmed"] is True
    assert result["deleted_counts"]["workflow_runtime_revisions"] == 1
    assert all(value == 0 for value in result["remaining_counts"].values())
    assert result["pending_cleanup"] == []
    assert (storage_root / "workflows" / "projects").is_dir()
    assert (storage_root / "workflows" / "runtime").is_dir()
    assert not (storage_root / "projects" / "project-1" / "workflow").exists()
    assert not (storage_root / "runtime" / "inputs" / "runtime-1").exists()
    assert not (buffer_root / "local-message" / "workflow-trigger").exists()
    assert (storage_root / "runtime" / "inputs" / "inference" / "keep.png").is_file()
    assert (buffer_root / "local-message" / "inference" / "mailbox.mmap").is_file()
    assert (buffer_root / "local-buffer" / "images.mmap").is_file()

    verification_factory = SessionFactory(settings.to_database_settings())
    with verification_factory.create_session() as session:
        assert _count(session, ModelRecord) == 1
        for entity in _workflow_entities():
            assert _count(session, entity) == 0
    verification_factory.engine.dispose()


def test_reset_development_workflow_state_rejects_active_resources(
    tmp_path: Path,
) -> None:
    """验证活动 Runtime 存在时确认重置仍会在任何写入前失败。"""

    settings, storage_root, _ = _build_settings(tmp_path)
    session_factory = SessionFactory(settings.to_database_settings())
    initialize_database_schema(session_factory)
    _seed_stopped_workflow_state(session_factory)
    with session_factory.create_session() as session:
        runtime = session.get(WorkflowAppRuntimeRecord, "runtime-1")
        assert runtime is not None
        runtime.desired_state = "running"
        runtime.observed_state = "running"
        session.commit()
    session_factory.engine.dispose()
    marker = storage_root / "workflows" / "runtime" / "keep.json"
    _write_marker(marker)

    with pytest.raises(RuntimeError, match="必须先停止全部 Runtime"):
        reset_development_workflow_state(
            request=DevelopmentWorkflowResetRequest(confirm=True),
            backend_service_settings=settings,
        )

    assert marker.is_file()
    verification_factory = SessionFactory(settings.to_database_settings())
    with verification_factory.create_session() as session:
        assert _count(session, WorkflowAppRuntimeRecord) == 1
    verification_factory.engine.dispose()


def test_reset_development_workflow_state_restores_files_on_database_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证数据库清理失败时已暂存的 Workflow 文件会恢复原位。"""

    settings, storage_root, buffer_root = _build_settings(tmp_path)
    session_factory = SessionFactory(settings.to_database_settings())
    initialize_database_schema(session_factory)
    session_factory.engine.dispose()
    workflow_marker = storage_root / "workflows" / "projects" / "marker.json"
    mailbox_marker = buffer_root / "local-message" / "workflow-trigger" / "mailbox.mmap"
    _write_marker(workflow_marker)
    _write_marker(mailbox_marker)

    def fail_delete(*, session_factory: SessionFactory) -> dict[str, int]:
        del session_factory
        raise RuntimeError("injected database failure")

    monkeypatch.setattr(reset_module, "_delete_database_state", fail_delete)
    with pytest.raises(RuntimeError, match="injected database failure"):
        reset_development_workflow_state(
            request=DevelopmentWorkflowResetRequest(confirm=True),
            backend_service_settings=settings,
        )

    assert workflow_marker.is_file()
    assert mailbox_marker.is_file()
    assert not tuple(tmp_path.rglob("*.workflow-reset-*"))


def test_clear_development_workflow_history_preserves_published_resources(
    tmp_path: Path,
) -> None:
    """验证历史清理只删除执行记录和目录，保留 App v1、Runtime 与 Trigger。"""

    settings, storage_root, _ = _build_settings(tmp_path)
    session_factory = SessionFactory(settings.to_database_settings())
    initialize_database_schema(session_factory)
    _seed_stopped_workflow_state(session_factory)
    with session_factory.create_session() as session:
        trigger = session.get(WorkflowTriggerSourceRecord, "trigger-1")
        runtime = session.get(WorkflowAppRuntimeRecord, "runtime-1")
        assert trigger is not None and runtime is not None
        trigger.last_triggered_at = "2026-08-31T01:00:00Z"
        trigger.last_error = "old trigger error"
        trigger.health_summary_json = {"request_count": 3}
        runtime.last_error = "old runtime error"
        runtime.health_summary_json = {"request_count": 3}
        session.commit()
    session_factory.engine.dispose()
    run_marker = storage_root / "workflows" / "runtime" / "workflow-run-run-1" / "events.jsonl"
    app_runtime_marker = (
        storage_root / "workflows" / "runtime" / "app-runtimes" / "runtime-1" / "events.jsonl"
    )
    result_marker = (
        storage_root
        / "projects"
        / "project-1"
        / "results"
        / "workflow-applications"
        / "app-1"
        / "result.json"
    )
    _write_marker(run_marker)
    _write_marker(app_runtime_marker)
    _write_marker(result_marker)

    result = clear_development_workflow_history(
        request=DevelopmentWorkflowHistoryClearRequest(confirm=True),
        backend_service_settings=settings,
    )

    assert result["deleted_counts"] == {
        "workflow_runs": 1,
        "workflow_preview_runs": 1,
    }
    assert result["pending_cleanup"] == []
    assert not run_marker.exists()
    assert not result_marker.exists()
    assert app_runtime_marker.is_file()
    verification_factory = SessionFactory(settings.to_database_settings())
    with verification_factory.create_session() as session:
        assert _count(session, WorkflowRunRecord) == 0
        assert _count(session, WorkflowPreviewRunRecord) == 0
        assert _count(session, WorkflowAppVersionRecord) == 1
        assert _count(session, WorkflowAppRuntimeRecord) == 1
        assert _count(session, WorkflowRuntimeRevisionRecord) == 1
        assert _count(session, WorkflowTriggerSourceRecord) == 1
        trigger = session.get(WorkflowTriggerSourceRecord, "trigger-1")
        runtime = session.get(WorkflowAppRuntimeRecord, "runtime-1")
        assert trigger is not None and runtime is not None
        assert trigger.last_triggered_at is None
        assert trigger.last_error is None
        assert trigger.health_summary_json == {}
        assert runtime.last_error is None
        assert runtime.health_summary_json == {}
    verification_factory.engine.dispose()


def _build_settings(tmp_path: Path) -> tuple[SimpleNamespace, Path, Path]:
    """创建隔离的重置测试配置。"""

    database_path = tmp_path / "database" / "amvision.db"
    storage_root = tmp_path / "files"
    buffer_root = tmp_path / "buffers"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    settings = SimpleNamespace(
        local_memory=SimpleNamespace(root_dir=str(buffer_root)),
        to_database_settings=lambda: DatabaseSettings(
            url=f"sqlite+pysqlite:///{database_path.as_posix()}"
        ),
        to_dataset_storage_settings=lambda: DatasetStorageSettings(
            root_dir=str(storage_root)
        ),
    )
    return settings, storage_root, buffer_root


def _seed_stopped_workflow_state(session_factory: SessionFactory) -> None:
    """写入覆盖全部 Workflow ORM 表的停止态测试数据。"""

    with session_factory.create_session() as session:
        session.add(
            ModelRecord(
                model_id="model-keep",
                project_id="project-1",
                owner_key="project-1",
                scope_kind="project",
                model_name="keep",
                model_type="yolo11",
                task_type="classification",
                model_scale="s",
            )
        )
        session.add(
            WorkflowAppVersionRecord(
                workflow_app_version_id="version-1",
                project_id="project-1",
                application_id="app-1",
                version_number=1,
                display_version="v1",
                application_snapshot_object_key="workflows/app.json",
                template_snapshot_object_key="workflows/template.json",
                contract_snapshot_object_key="workflows/contract.json",
                dependency_manifest_object_key="workflows/dependencies.json",
                content_fingerprint="content-1",
                contract_fingerprint="contract-1",
                state="ready",
                created_at="2026-08-31T00:00:00Z",
            )
        )
        session.add(
            WorkflowAppRuntimeRecord(
                workflow_runtime_id="runtime-1",
                project_id="project-1",
                application_id="app-1",
                application_snapshot_object_key="workflows/runtime/app.json",
                template_snapshot_object_key="workflows/runtime/template.json",
                desired_state="stopped",
                observed_state="stopped",
                created_at="2026-08-31T00:00:00Z",
                updated_at="2026-08-31T00:00:00Z",
            )
        )
        session.flush()
        session.add_all(
            (
                WorkflowRuntimeRevisionRecord(
                    workflow_runtime_revision_id="revision-1",
                    workflow_runtime_id="runtime-1",
                    generation=1,
                    workflow_app_version_id="version-1",
                    expected_snapshot_fingerprint="snapshot-1",
                    state="active",
                    created_at="2026-08-31T00:00:00Z",
                ),
                WorkflowTriggerSourceRecord(
                    trigger_source_id="trigger-1",
                    project_id="project-1",
                    trigger_kind="local-shared-memory",
                    workflow_runtime_id="runtime-1",
                    submit_mode="sync",
                    enabled=False,
                    desired_state="stopped",
                    observed_state="stopped",
                    created_at="2026-08-31T00:00:00Z",
                    updated_at="2026-08-31T00:00:00Z",
                ),
                WorkflowRunRecord(
                    workflow_run_id="run-1",
                    workflow_runtime_id="runtime-1",
                    project_id="project-1",
                    application_id="app-1",
                    state="succeeded",
                    created_at="2026-08-31T00:00:00Z",
                ),
                WorkflowPreviewRunRecord(
                    preview_run_id="preview-1",
                    project_id="project-1",
                    application_id="app-1",
                    source_kind="application",
                    application_snapshot_object_key="workflows/preview/app.json",
                    template_snapshot_object_key="workflows/preview/template.json",
                    state="succeeded",
                    created_at="2026-08-31T00:00:00Z",
                ),
                WorkflowApplicationLifecycleRecord(
                    project_id="project-1",
                    application_id="app-1",
                    state="active",
                    generation=1,
                    updated_at="2026-08-31T00:00:00Z",
                ),
                WorkflowExecutionPolicyRecord(
                    execution_policy_id="policy-1",
                    project_id="project-1",
                    policy_kind="runtime-default",
                    created_at="2026-08-31T00:00:00Z",
                    updated_at="2026-08-31T00:00:00Z",
                ),
            )
        )
        session.commit()


def _workflow_entities() -> tuple[type, ...]:
    """返回重置覆盖的全部 Workflow ORM 实体。"""

    return (
        WorkflowTriggerSourceRecord,
        WorkflowRunRecord,
        WorkflowAppRuntimeRecord,
        WorkflowRuntimeRevisionRecord,
        WorkflowAppVersionRecord,
        WorkflowApplicationLifecycleRecord,
        WorkflowPreviewRunRecord,
        WorkflowExecutionPolicyRecord,
    )


def _write_marker(path: Path) -> None:
    """创建隔离测试使用的标记文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("test", encoding="utf-8")


def _count(session: object, entity: type) -> int:
    """统计 ORM 实体记录数量。"""

    return int(session.scalar(select(func.count()).select_from(entity)) or 0)
