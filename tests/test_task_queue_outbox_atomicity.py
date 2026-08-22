"""TaskRecord 与 Queue Outbox 原子提交测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.service.application.errors import (
    InvalidRequestError,
    PersistenceOperationError,
    ResourceNotFoundError,
)
from backend.service.application.tasks.task_service import (
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskQueueSubmission,
)
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


def test_task_and_queue_outbox_are_committed_in_one_transaction(tmp_path: Path) -> None:
    """创建任务时同时持久化确定性队列消息和公开队列元数据。"""

    session_factory = _create_session_factory(tmp_path)
    service = SqlAlchemyTaskService(session_factory)
    created = service.create_task(
        CreateTaskRequest(
            task_id="task-atomic-1",
            project_id="project-1",
            task_kind="training",
            metadata={"model_id": "model-1"},
            queue_submission=TaskQueueSubmission(
                queue_name="training",
                payload={"task_kind": "training"},
                metadata={"project_id": "project-1"},
            ),
        )
    )

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        stored_task = unit_of_work.tasks.get_task(created.task_id)
        outbox = unit_of_work.queue_outbox.get_message(
            "queue-message-task-atomic-1"
        )
        events = unit_of_work.tasks.list_task_events(created.task_id)
    finally:
        unit_of_work.close()

    assert stored_task is not None
    assert stored_task.metadata["queue_name"] == "training"
    assert stored_task.metadata["queue_task_id"] == "queue-message-task-atomic-1"
    assert outbox is not None
    assert outbox.payload == {
        "task_id": "task-atomic-1",
        "task_kind": "training",
        "attempt_no": 1,
    }
    assert outbox.metadata == {"project_id": "project-1"}
    assert events[0].payload["metadata"] == {
        "queue_name": "training",
        "queue_task_id": "queue-message-task-atomic-1",
    }


def test_outbox_conflict_rolls_back_the_second_task(tmp_path: Path) -> None:
    """Outbox 唯一键冲突时 TaskRecord 不得单独提交。"""

    session_factory = _create_session_factory(tmp_path)
    service = SqlAlchemyTaskService(session_factory)
    first_submission = TaskQueueSubmission(
        queue_name="training",
        message_id="stable-message-1",
    )
    service.create_task(
        CreateTaskRequest(
            task_id="task-first",
            project_id="project-1",
            task_kind="training",
            queue_submission=first_submission,
        )
    )

    with pytest.raises(PersistenceOperationError):
        service.create_task(
            CreateTaskRequest(
                task_id="task-second",
                project_id="project-1",
                task_kind="training",
                queue_submission=TaskQueueSubmission(
                    queue_name="training",
                    message_id="stable-message-1",
                ),
            )
        )

    with pytest.raises(ResourceNotFoundError):
        service.get_task("task-second")


def test_queue_payload_cannot_target_another_task(tmp_path: Path) -> None:
    """拒绝把稳定消息关联到与 TaskRecord 不同的 task_id。"""

    session_factory = _create_session_factory(tmp_path)
    service = SqlAlchemyTaskService(session_factory)
    with pytest.raises(InvalidRequestError, match="task_id"):
        service.create_task(
            CreateTaskRequest(
                task_id="task-expected",
                project_id="project-1",
                task_kind="training",
                queue_submission=TaskQueueSubmission(
                    queue_name="training",
                    payload={"task_id": "task-other"},
                ),
            )
        )


def _create_session_factory(tmp_path: Path) -> SessionFactory:
    """创建完整 schema 的隔离 SQLite 数据库。"""

    session_factory = SessionFactory(
        DatabaseSettings(url=f"sqlite:///{(tmp_path / 'task-outbox.db').as_posix()}")
    )
    initialize_database_schema(session_factory)
    return session_factory
