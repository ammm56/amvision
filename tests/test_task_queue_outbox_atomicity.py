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
    AppendTaskEventRequest,
    CreateTaskRequest,
    ResumeTaskRequest,
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


def test_resume_task_and_queue_outbox_are_committed_atomically(tmp_path: Path) -> None:
    """恢复状态、事件和下一 Attempt 队列消息必须在同一事务提交。"""

    session_factory = _create_session_factory(tmp_path)
    service = SqlAlchemyTaskService(session_factory)
    _create_paused_attempt(service, task_id="task-resume-1")

    submission = service.resume_task_with_outbox(
        ResumeTaskRequest(
            task_id="task-resume-1",
            expected_states=("paused",),
            expected_current_attempt_no=1,
            queue_submission=TaskQueueSubmission(
                queue_name="training",
                payload={"task_kind": "training"},
                metadata={"project_id": "project-1"},
            ),
            progress_patch={"stage": "queued"},
            result_patch={"status": "queued"},
        )
    )

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        stored_task = unit_of_work.tasks.get_task("task-resume-1")
        outbox = unit_of_work.queue_outbox.get_message(submission.queue_task_id)
        events = unit_of_work.tasks.list_task_events("task-resume-1")
    finally:
        unit_of_work.close()

    assert stored_task is not None
    assert stored_task.state == "queued"
    assert stored_task.current_attempt_no == 1
    assert stored_task.finished_at is None
    assert stored_task.error_message is None
    assert stored_task.metadata["queue_task_id"] == submission.queue_task_id
    assert stored_task.result["queue_task_id"] == submission.queue_task_id
    assert outbox is not None
    assert outbox.payload == {
        "task_id": "task-resume-1",
        "task_kind": "training",
        "attempt_no": 2,
    }
    resume_event = next(event for event in events if event.message == "task resume queued")
    assert resume_event.payload["attempt_no"] == 2
    assert submission.queue_task_id.startswith("queue-resume-")
    assert len(submission.queue_task_id) == len("queue-resume-") + 32

    with pytest.raises(InvalidRequestError, match="恢复请求未生效"):
        service.resume_task_with_outbox(
            ResumeTaskRequest(
                task_id="task-resume-1",
                expected_states=("paused",),
                expected_current_attempt_no=1,
                queue_submission=TaskQueueSubmission(queue_name="training"),
            )
        )


def test_resume_outbox_conflict_rolls_back_task_state(tmp_path: Path) -> None:
    """恢复 outbox 写入冲突时 queued 状态和恢复事件不得单独提交。"""

    session_factory = _create_session_factory(tmp_path)
    service = SqlAlchemyTaskService(session_factory)
    service.create_task(
        CreateTaskRequest(
            task_id="outbox-owner",
            project_id="project-1",
            task_kind="training",
            queue_submission=TaskQueueSubmission(
                queue_name="training",
                message_id="conflicting-resume-message",
            ),
        )
    )
    _create_paused_attempt(service, task_id="task-resume-conflict")
    event_count = len(
        service.get_task("task-resume-conflict", include_events=True).events
    )

    with pytest.raises(PersistenceOperationError):
        service.resume_task_with_outbox(
            ResumeTaskRequest(
                task_id="task-resume-conflict",
                expected_states=("paused",),
                expected_current_attempt_no=1,
                queue_submission=TaskQueueSubmission(
                    queue_name="training",
                    message_id="conflicting-resume-message",
                ),
            )
        )

    detail = service.get_task("task-resume-conflict", include_events=True)
    assert detail.task.state == "paused"
    assert len(detail.events) == event_count


def test_plain_task_event_is_append_only_and_rejects_snapshot_fields(
    tmp_path: Path,
) -> None:
    """普通事件只追加审计记录，不能隐式修改 Task 快照。"""

    session_factory = _create_session_factory(tmp_path)
    service = SqlAlchemyTaskService(session_factory)
    created = service.create_task(
        CreateTaskRequest(
            task_id="task-plain-event",
            project_id="project-1",
            task_kind="training",
        )
    )

    detail = service.append_task_event(
        AppendTaskEventRequest(
            task_id=created.task_id,
            event_type="log",
            message="diagnostic sample",
            payload={"diagnostic": {"device": "cpu"}},
        )
    )
    assert detail.task == created
    assert detail.events[0].payload == {"diagnostic": {"device": "cpu"}}

    with pytest.raises(InvalidRequestError, match="不能修改 Task 快照"):
        service.append_task_event(
            AppendTaskEventRequest(
                task_id=created.task_id,
                event_type="progress",
                payload={"progress": {"epoch": 1}},
            )
        )


def _create_paused_attempt(
    service: SqlAlchemyTaskService,
    *,
    task_id: str,
) -> None:
    """创建并由统一 finalizer 暂停第一个执行 Attempt。"""

    service.create_task(
        CreateTaskRequest(
            task_id=task_id,
            project_id="project-1",
            task_kind="training",
        )
    )
    claim = service.claim_task_execution(
        task_id=task_id,
        attempt_no=1,
        worker_id="worker-1",
        queue_name="training",
        queue_message_id=f"queue-message-{task_id}",
        queue_attempt_count=1,
        queue_leased_at="2026-08-24T00:00:00+00:00",
    )
    assert claim.attempt is not None
    service.finalize_task_execution_attempt(
        attempt_id=claim.attempt.attempt_id,
        attempt_outcome="paused",
        result={"status": "paused"},
        error_message=None,
        metadata=None,
        expected_worker_id="worker-1",
        expected_heartbeat_at="2026-08-24T00:00:00+00:00",
        expected_queue_message_id=f"queue-message-{task_id}",
        expected_queue_attempt_count=1,
    )


def _create_session_factory(tmp_path: Path) -> SessionFactory:
    """创建完整 schema 的隔离 SQLite 数据库。"""

    session_factory = SessionFactory(
        DatabaseSettings(url=f"sqlite:///{(tmp_path / 'task-outbox.db').as_posix()}")
    )
    initialize_database_schema(session_factory)
    return session_factory
