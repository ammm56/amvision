"""Transactional Outbox dispatcher 崩溃窗口与重试测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.service.application.errors import PersistenceOperationError
from backend.service.application.tasks.queue_outbox import (
    QueueOutboxDispatcher,
    QueueOutboxDispatcherSettings,
    build_queue_outbox_message,
)
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.queue.local_file import (
    LocalFileQueueBackend,
    LocalFileQueueSettings,
)


def test_queue_outbox_rejects_non_finite_json_number() -> None:
    """Outbox 在写数据库前拒绝无法跨后端稳定表示的 NaN。"""

    with pytest.raises(PersistenceOperationError, match="合法 JSON"):
        build_queue_outbox_message(
            message_id="queue-message-task-1",
            queue_name="training",
            payload={"metric": float("nan")},
        )


@pytest.mark.parametrize("queue_name", ("../training", "CON", "x" * 129))
def test_queue_outbox_rejects_invalid_queue_name(queue_name: str) -> None:
    """Outbox 在业务事务前拒绝文件队列无法安全表示的名称。"""

    with pytest.raises(PersistenceOperationError, match="队列名不合法"):
        build_queue_outbox_message(
            message_id="queue-message-task-1",
            queue_name=queue_name,
            payload={"task_id": "task-1"},
        )


def test_queue_outbox_dispatches_and_marks_message_in_separate_transactions(
    tmp_path: Path,
) -> None:
    """业务事务提交的消息可被写入文件队列并独立确认 dispatched。"""

    session_factory = _create_session_factory(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    _save_outbox_message(session_factory, message_id="queue-message-task-1")
    dispatcher = QueueOutboxDispatcher(
        session_factory=session_factory,
        queue_backend=queue_backend,
        dispatcher_id="dispatcher-a",
    )

    dispatched_count = dispatcher.dispatch_once(
        now=datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    )

    assert dispatched_count == 1
    queue_message = queue_backend.get_task(
        queue_name="training",
        task_id="queue-message-task-1",
    )
    assert queue_message is not None
    assert queue_message.payload == {"task_id": "task-1"}
    stored = _get_outbox_message(session_factory, "queue-message-task-1")
    assert stored.state == "dispatched"
    assert stored.attempt_count == 1


def test_queue_outbox_stop_finishes_already_claimed_batch(tmp_path: Path) -> None:
    """停止信号不能遗留同一批已领取但尚未投递的消息 lease。"""

    session_factory = _create_session_factory(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    _save_outbox_message(session_factory, message_id="queue-message-task-1")
    _save_outbox_message(session_factory, message_id="queue-message-task-2")
    dispatcher: QueueOutboxDispatcher

    class _StopAfterFirstEnqueue:
        def __init__(self) -> None:
            self.enqueue_count = 0

        def enqueue(self, **kwargs: object) -> object:
            self.enqueue_count += 1
            result = queue_backend.enqueue(**kwargs)  # type: ignore[arg-type]
            if self.enqueue_count == 1:
                dispatcher.stop()
            return result

    stopping_queue = _StopAfterFirstEnqueue()
    dispatcher = QueueOutboxDispatcher(
        session_factory=session_factory,
        queue_backend=stopping_queue,  # type: ignore[arg-type]
        dispatcher_id="dispatcher-stop",
    )

    assert (
        dispatcher.dispatch_once(now=datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc))
        == 2
    )
    assert stopping_queue.enqueue_count == 2
    assert (
        _get_outbox_message(session_factory, "queue-message-task-1").state
        == "dispatched"
    )
    assert (
        _get_outbox_message(session_factory, "queue-message-task-2").state
        == "dispatched"
    )


def test_queue_outbox_replay_after_enqueue_crash_window_is_idempotent(
    tmp_path: Path,
) -> None:
    """文件已入队但 DB 未确认时，租约到期重投不能生成第二条任务。"""

    session_factory = _create_session_factory(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    message = _save_outbox_message(
        session_factory,
        message_id="queue-message-task-1",
    )
    with session_factory.create_session() as session:
        unit_of_work = SqlAlchemyUnitOfWork(session)
        claimed = unit_of_work.queue_outbox.claim_available_messages(
            lease_owner="crashed-dispatcher",
            claimed_at="2026-08-20T09:59:00+00:00",
            lease_expires_at="2026-08-20T09:59:10+00:00",
            limit=1,
        )
        unit_of_work.commit()
    assert len(claimed) == 1
    queue_backend.enqueue(
        queue_name=message.queue_name,
        payload=message.payload,
        metadata=message.metadata,
        message_id=message.message_id,
    )

    dispatcher = QueueOutboxDispatcher(
        session_factory=session_factory,
        queue_backend=queue_backend,
        dispatcher_id="recovery-dispatcher",
    )
    assert (
        dispatcher.dispatch_once(now=datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc))
        == 1
    )

    pending_files = tuple((tmp_path / "queue" / "training" / "pending").glob("*.json"))
    assert tuple(path.name for path in pending_files) == ("queue-message-task-1.json",)
    stored = _get_outbox_message(session_factory, "queue-message-task-1")
    assert stored.state == "dispatched"
    assert stored.attempt_count == 2


def test_queue_outbox_failed_delivery_is_released_with_backoff(tmp_path: Path) -> None:
    """队列暂时失败时消息回到 pending，且不会在同一时刻忙循环。"""

    session_factory = _create_session_factory(tmp_path)
    _save_outbox_message(session_factory, message_id="queue-message-task-1")

    class _FailingQueue:
        def enqueue(self, **_kwargs: object) -> object:
            raise OSError("queue unavailable")

    dispatcher = QueueOutboxDispatcher(
        session_factory=session_factory,
        queue_backend=_FailingQueue(),  # type: ignore[arg-type]
        settings=QueueOutboxDispatcherSettings(
            retry_base_seconds=2.0,
            retry_max_seconds=2.0,
        ),
        dispatcher_id="dispatcher-a",
    )
    assert (
        dispatcher.dispatch_once(now=datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc))
        == 0
    )

    stored = _get_outbox_message(session_factory, "queue-message-task-1")
    assert stored.state == "pending"
    assert stored.available_at == "2026-08-20T10:00:02+00:00"
    assert stored.last_error == "queue unavailable"
    assert (
        dispatcher.dispatch_once(
            now=datetime(2026, 8, 20, 10, 0, 1, tzinfo=timezone.utc)
        )
        == 0
    )
    assert (
        _get_outbox_message(session_factory, "queue-message-task-1").attempt_count == 1
    )


def _create_session_factory(tmp_path: Path) -> SessionFactory:
    """创建 Outbox 集成测试数据库。"""

    session_factory = SessionFactory(
        DatabaseSettings(url=f"sqlite:///{(tmp_path / 'dispatcher.db').as_posix()}")
    )
    initialize_database_schema(session_factory)
    return session_factory


def _save_outbox_message(
    session_factory: SessionFactory,
    *,
    message_id: str,
):
    """在独立业务事务中保存一条测试 Outbox 消息。"""

    message = build_queue_outbox_message(
        message_id=message_id,
        queue_name="training",
        payload={"task_id": "task-1"},
        metadata={"project_id": "project-1"},
        created_at="2026-08-20T09:59:00+00:00",
    )
    with session_factory.create_session() as session:
        unit_of_work = SqlAlchemyUnitOfWork(session)
        unit_of_work.queue_outbox.add_message(message)
        unit_of_work.commit()
    return message


def _get_outbox_message(session_factory: SessionFactory, message_id: str):
    """读取测试消息并断言存在。"""

    with session_factory.create_session() as session:
        unit_of_work = SqlAlchemyUnitOfWork(session)
        message = unit_of_work.queue_outbox.get_message(message_id)
    assert message is not None
    return message
