"""异步删除清单、物理清理消费者和回执的验收。"""

from backend.workers.resource_cleanup import ResourceCleanupWorker
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests import test_resource_deletion_service as deletion_fixtures

deletion_runtime = deletion_fixtures.deletion_runtime


def test_async_delete_waits_for_worker_and_keeps_completion_receipt(deletion_runtime):
    """202 对应已提交，只有消费者清理暂存后才转为 completed。"""
    service, factory, storage, queue = deletion_runtime
    operation_id = service.delete(
        kind="task",
        resource_id="task-delete",
        project_id="project-1",
        asynchronous=True,
    )
    staging = storage.resolve(f"runtime/resource-deletion-staging/{operation_id}")
    assert staging.is_dir()
    with factory.create_session() as session:
        unit = SqlAlchemyUnitOfWork(session)
        assert unit.tasks.get_task("task-delete") is None
        assert unit.resource_deletions.get(operation_id).state == "committed"
    worker = ResourceCleanupWorker(
        session_factory=factory,
        dataset_storage=storage,
        queue_backend=queue,
        worker_id="test-cleanup",
    )
    assert worker.run_once()
    assert not staging.exists()
    with factory.create_session() as session:
        operation = SqlAlchemyUnitOfWork(session).resource_deletions.get(operation_id)
        assert operation.state == "completed"
        assert operation.plan.paths == []
        assert operation.plan.records == []
    service.retry(operation_id)


def test_cleanup_failure_does_not_lose_plan_or_retry_forever(
    deletion_runtime, monkeypatch
):
    """占用故障保留独立记录并退避，下轮成功后完成。"""
    service, factory, storage, queue = deletion_runtime
    operation_id = service.delete(
        kind="task",
        resource_id="task-delete",
        project_id="project-1",
        asynchronous=True,
    )
    original = storage.delete_tree

    def occupied(path):
        """模拟已提交后的磁盘占用。"""
        raise PermissionError("occupied")

    monkeypatch.setattr(storage, "delete_tree", occupied)
    worker = ResourceCleanupWorker(
        session_factory=factory,
        dataset_storage=storage,
        queue_backend=queue,
        worker_id="test-cleanup",
    )
    assert not worker.run_once()
    assert not worker.run_once()
    with factory.create_session() as session:
        operation = SqlAlchemyUnitOfWork(session).resource_deletions.get(operation_id)
        assert operation.state == "committed" and "occupied" in operation.error
    monkeypatch.setattr(storage, "delete_tree", original)
    worker.next_poll_at = 0
    assert worker.run_once()
