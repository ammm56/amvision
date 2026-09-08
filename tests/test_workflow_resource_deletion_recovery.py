"""Workflow Runtime/Trigger 物理删除暂存恢复测试。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.workflows.resource_deletion_recovery import (
    WorkflowResourceDeletionRecoveryService,
)
from backend.service.application.workflows.resource_deletion_staging import (
    stage_workflow_resource_storage,
)
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
)
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.api_test_support import create_test_runtime


def test_startup_recovery_restores_uncommitted_runtime_delete(
    tmp_path: Path,
) -> None:
    """数据库 Runtime 仍存在时，把异常中断后暂存的目录恢复原位。"""

    factory, storage, _queue = create_test_runtime(
        tmp_path,
        database_name="runtime-delete-recovery.db",
    )
    runtime_id = "workflow-runtime-recovery"
    runtime_dir = f"workflows/runtime/app-runtimes/{runtime_id}"
    storage.write_json(f"{runtime_dir}/state.json", {"state": "stopped"})
    unit_of_work = SqlAlchemyUnitOfWork(factory.create_session())
    try:
        unit_of_work.workflow_runtime.save_workflow_app_runtime(
            WorkflowAppRuntime(
                workflow_runtime_id=runtime_id,
                project_id="project-1",
                application_id="workflow-app-recovery",
                display_name="Recovery Runtime",
                application_snapshot_object_key=(
                    f"{runtime_dir}/application.snapshot.json"
                ),
                template_snapshot_object_key=f"{runtime_dir}/template.snapshot.json",
                desired_state="stopped",
                observed_state="stopped",
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()
    staging = stage_workflow_resource_storage(
        dataset_storage=storage,
        operation_id="runtime-delete-interrupted",
        resource_kind="workflow-runtime",
        resource_id=runtime_id,
        source_paths=(runtime_dir,),
    )
    assert not storage.resolve(runtime_dir).exists()
    assert storage.resolve(staging.staging_root).is_dir()

    result = WorkflowResourceDeletionRecoveryService(
        session_factory=factory,
        dataset_storage=storage,
    ).recover()

    assert result.restored_deletions == 1
    assert result.completed_cleanups == 0
    assert storage.resolve(f"{runtime_dir}/state.json").is_file()
    assert not storage.resolve(staging.staging_root).exists()
    factory.engine.dispose()


def test_startup_recovery_finishes_committed_trigger_delete(tmp_path: Path) -> None:
    """数据库 Trigger 已不存在时，只清理已提交删除留下的暂存目录。"""

    factory, storage, _queue = create_test_runtime(
        tmp_path,
        database_name="trigger-delete-recovery.db",
    )
    trigger_id = "trigger-source-recovery"
    trigger_dir = f"workflows/runtime/trigger-sources/{trigger_id}"
    storage.write_json(f"{trigger_dir}/state.json", {"state": "stopped"})
    staging = stage_workflow_resource_storage(
        dataset_storage=storage,
        operation_id="trigger-delete-committed",
        resource_kind="workflow-trigger",
        resource_id=trigger_id,
        source_paths=(trigger_dir,),
    )
    assert storage.resolve(staging.staging_root).is_dir()

    result = WorkflowResourceDeletionRecoveryService(
        session_factory=factory,
        dataset_storage=storage,
    ).recover()

    assert result.restored_deletions == 0
    assert result.completed_cleanups == 1
    assert not storage.resolve(trigger_dir).exists()
    assert not storage.resolve(staging.staging_root).exists()
    factory.engine.dispose()
