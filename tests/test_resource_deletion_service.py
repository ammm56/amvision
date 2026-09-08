"""完整资源删除与中断恢复的隔离数据库/磁盘验证。"""

from pathlib import Path

import pytest

from backend.service.application.errors import PersistenceOperationError, ResourceInUseError
from backend.service.application.resource_deletion import ResourceDeletionService
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.persistence.resource_deletion_repository import ResourceDeletionRepository
from tests.api_test_support import create_test_runtime


@pytest.fixture
def deletion_runtime(tmp_path: Path):
    """每项测试独立的数据库、队列和文件根。"""
    factory, storage, queue = create_test_runtime(tmp_path, database_name="delete.db")
    unit = SqlAlchemyUnitOfWork(factory.create_session())
    unit.tasks.save_task(TaskRecord(task_id="task-delete", task_kind="model.evaluation", project_id="project-1", state="failed"))
    unit.commit()
    unit.close()
    storage.write_bytes("task-runs/evaluation/task-delete/result.bin", b"prediction")
    service = ResourceDeletionService(session_factory=factory, dataset_storage=storage, queue_backend=queue)
    yield service, factory, storage, queue
    factory.engine.dispose()


def test_delete_failed_task_without_result_cleans_files_and_queue(deletion_runtime) -> None:
    """失败任务没有 result 时仍清除确定归属的目录和终态消息。"""
    service, factory, storage, queue = deletion_runtime
    queue.enqueue(queue_name="test-delete", payload={"task_id": "task-delete"})
    message = queue.claim_next(queue_name="test-delete", worker_id="worker-1")
    queue.complete(message)
    service.delete(kind="task", resource_id="task-delete", project_id="project-1")
    assert not storage.resolve("task-runs/evaluation/task-delete").exists()
    assert queue.list_tasks_by_references(references=(("task_id", "task-delete"),)) == ()
    unit = SqlAlchemyUnitOfWork(factory.create_session())
    assert unit.tasks.get_task("task-delete") is None
    assert unit.resource_deletions.list_pending() == []
    unit.close()


def test_delete_task_database_failure_restores_files(deletion_runtime, monkeypatch) -> None:
    """数据库删除失败后恢复原文件，Task 与文件同时保留。"""
    service, factory, storage, _queue = deletion_runtime
    original = ResourceDeletionRepository.delete_records

    def fail_after_delete(repository, references):
        """模拟数据库操作已执行但提交前失败。"""
        original(repository, references)
        raise RuntimeError("database failure")

    monkeypatch.setattr(ResourceDeletionRepository, "delete_records", fail_after_delete)
    with pytest.raises(RuntimeError, match="database failure"):
        service.delete(kind="task", resource_id="task-delete", project_id="project-1")
    assert storage.resolve("task-runs/evaluation/task-delete/result.bin").read_bytes() == b"prediction"
    unit = SqlAlchemyUnitOfWork(factory.create_session())
    assert unit.tasks.get_task("task-delete") is not None
    assert unit.resource_deletions.list_pending() == []
    unit.close()


def test_committed_cleanup_failure_remains_retryable(deletion_runtime, monkeypatch) -> None:
    """物理清理失败保留独立恢复记录，重试不需要原 Task。"""
    service, factory, storage, _queue = deletion_runtime
    original = storage.delete_tree

    def occupied(path):
        """模拟 Windows 删除暂存目录时有文件占用。"""
        if path.startswith("runtime/resource-deletion-staging/"):
            raise PermissionError("occupied")
        original(path)

    monkeypatch.setattr(storage, "delete_tree", occupied)
    with pytest.raises(PersistenceOperationError):
        service.delete(kind="task", resource_id="task-delete", project_id="project-1")
    unit = SqlAlchemyUnitOfWork(factory.create_session())
    assert unit.tasks.get_task("task-delete") is None
    operations = unit.resource_deletions.list_pending()
    assert len(operations) == 1 and operations[0].state == "committed"
    unit.close()
    monkeypatch.setattr(storage, "delete_tree", original)
    service.retry(operations[0].plan.operation_id)
    unit = SqlAlchemyUnitOfWork(factory.create_session())
    assert unit.resource_deletions.list_pending() == []
    unit.close()


def test_delete_rejects_live_queue_before_moving_files(deletion_runtime) -> None:
    """Task 终态与队列不一致时，删除不能破坏尚有生产者的目录。"""
    service, _factory, storage, queue = deletion_runtime
    queue.enqueue(queue_name="test-delete", payload={"task_id": "task-delete"})
    with pytest.raises(ResourceInUseError):
        service.delete(kind="task", resource_id="task-delete", project_id="project-1")
    assert storage.resolve("task-runs/evaluation/task-delete/result.bin").exists()


def test_delete_rejects_other_task_input_reference(deletion_runtime) -> None:
    """跨任务输入依赖阻止整个删除，已停止也不能留下失效引用。"""
    service, factory, storage, _queue = deletion_runtime
    unit = SqlAlchemyUnitOfWork(factory.create_session())
    unit.tasks.save_task(TaskRecord(task_id="task-child", task_kind="model.evaluation", project_id="project-2", state="failed", task_spec={"parent_task_id": "task-delete"}))
    unit.commit()
    unit.close()
    with pytest.raises(ResourceInUseError):
        service.delete(kind="task", resource_id="task-delete", project_id="project-1")
    assert storage.resolve("task-runs/evaluation/task-delete/result.bin").exists()
