"""Transactional Outbox 仓储租约与 CAS 测试。"""

from __future__ import annotations

from pathlib import Path

from backend.service.domain.tasks.outbox_records import QueueOutboxMessage
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.persistence.queue_outbox_repository import (
    SqlAlchemyQueueOutboxRepository,
)


def test_queue_outbox_claim_and_dispatch_requires_current_lease_owner(
    tmp_path: Path,
) -> None:
    """只有当前 dispatcher 租约持有者能发布消息终态。"""

    session_factory = _create_session_factory(tmp_path)
    with session_factory.create_session() as session:
        repository = SqlAlchemyQueueOutboxRepository(session)
        repository.add_message(_build_message("outbox-1"))
        session.commit()

    with session_factory.create_session() as session:
        repository = SqlAlchemyQueueOutboxRepository(session)
        claimed = repository.claim_available_messages(
            lease_owner="dispatcher-a",
            claimed_at="2026-08-20T10:00:00+00:00",
            lease_expires_at="2026-08-20T10:00:30+00:00",
            limit=8,
        )
        session.commit()

    assert len(claimed) == 1
    assert claimed[0].state == "leased"
    assert claimed[0].lease_owner == "dispatcher-a"
    assert claimed[0].attempt_count == 1

    with session_factory.create_session() as session:
        repository = SqlAlchemyQueueOutboxRepository(session)
        assert (
            repository.mark_dispatched(
                message_id="outbox-1",
                lease_owner="dispatcher-b",
                dispatched_at="2026-08-20T10:00:01+00:00",
            )
            is False
        )
        assert repository.mark_dispatched(
            message_id="outbox-1",
            lease_owner="dispatcher-a",
            dispatched_at="2026-08-20T10:00:01+00:00",
        )
        session.commit()

    with session_factory.create_session() as session:
        stored = SqlAlchemyQueueOutboxRepository(session).get_message("outbox-1")
    assert stored is not None
    assert stored.state == "dispatched"
    assert stored.dispatched_at == "2026-08-20T10:00:01+00:00"
    assert stored.lease_owner is None


def test_queue_outbox_reclaims_expired_lease_and_rejects_stale_release(
    tmp_path: Path,
) -> None:
    """租约过期后允许新 dispatcher 接管，旧持有者不能覆盖新租约。"""

    session_factory = _create_session_factory(tmp_path)
    with session_factory.create_session() as session:
        repository = SqlAlchemyQueueOutboxRepository(session)
        repository.add_message(_build_message("outbox-1"))
        session.commit()

    with session_factory.create_session() as session:
        repository = SqlAlchemyQueueOutboxRepository(session)
        first_claim = repository.claim_available_messages(
            lease_owner="dispatcher-a",
            claimed_at="2026-08-20T10:00:00+00:00",
            lease_expires_at="2026-08-20T10:00:10+00:00",
            limit=8,
        )
        session.commit()
    assert first_claim[0].attempt_count == 1

    with session_factory.create_session() as session:
        repository = SqlAlchemyQueueOutboxRepository(session)
        assert (
            repository.claim_available_messages(
                lease_owner="dispatcher-b",
                claimed_at="2026-08-20T10:00:05+00:00",
                lease_expires_at="2026-08-20T10:00:35+00:00",
                limit=8,
            )
            == ()
        )
        session.commit()

    with session_factory.create_session() as session:
        repository = SqlAlchemyQueueOutboxRepository(session)
        second_claim = repository.claim_available_messages(
            lease_owner="dispatcher-b",
            claimed_at="2026-08-20T10:00:11+00:00",
            lease_expires_at="2026-08-20T10:00:41+00:00",
            limit=8,
        )
        session.commit()
    assert second_claim[0].attempt_count == 2
    assert second_claim[0].lease_owner == "dispatcher-b"

    with session_factory.create_session() as session:
        repository = SqlAlchemyQueueOutboxRepository(session)
        assert (
            repository.release_for_retry(
                message_id="outbox-1",
                lease_owner="dispatcher-a",
                available_at="2026-08-20T10:01:00+00:00",
                error_message="stale dispatcher",
            )
            is False
        )
        assert repository.release_for_retry(
            message_id="outbox-1",
            lease_owner="dispatcher-b",
            available_at="2026-08-20T10:01:00+00:00",
            error_message="queue temporarily unavailable",
        )
        session.commit()

    with session_factory.create_session() as session:
        stored = SqlAlchemyQueueOutboxRepository(session).get_message("outbox-1")
    assert stored is not None
    assert stored.state == "pending"
    assert stored.available_at == "2026-08-20T10:01:00+00:00"
    assert stored.last_error == "queue temporarily unavailable"


def _create_session_factory(tmp_path: Path) -> SessionFactory:
    """创建启用完整 ORM metadata 的文件 SQLite 测试数据库。"""

    session_factory = SessionFactory(
        DatabaseSettings(url=f"sqlite:///{(tmp_path / 'outbox.db').as_posix()}")
    )
    initialize_database_schema(session_factory)
    return session_factory


def _build_message(message_id: str) -> QueueOutboxMessage:
    """构造一条立即可领取的确定性测试消息。"""

    return QueueOutboxMessage(
        message_id=message_id,
        queue_name="training",
        payload={"task_id": "task-1"},
        metadata={"project_id": "project-1"},
        payload_fingerprint="a" * 64,
        created_at="2026-08-20T09:59:00+00:00",
        available_at="2026-08-20T09:59:00+00:00",
    )
