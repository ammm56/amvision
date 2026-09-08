"""Project 专属 Outbox 清理，覆盖没有 Task id 的消息。"""

import pytest
from sqlalchemy import select

from backend.service.application.errors import ResourceInUseError
from backend.service.infrastructure.persistence.project_deletion_repository import SqlAlchemyProjectDeletionRepository
from backend.service.infrastructure.persistence.queue_outbox_orm import QueueOutboxMessageEntity
from tests.api_test_support import create_test_runtime


@pytest.mark.parametrize("state", ["dispatched", "pending"])
def test_project_outbox_ownership_and_pending_protection(tmp_path, state):
    """只清理本 Project 的终态消息，待投递时整次事务回滚。"""
    factory, _storage, _queue = create_test_runtime(tmp_path, database_name="project-outbox.db")
    try:
        with factory.create_session() as session:
            for project_id in ("project-1", "project-2"):
                session.add(QueueOutboxMessageEntity(
                    message_id=project_id, queue_name="test", payload_json={"project_id": project_id},
                    metadata_json={}, payload_fingerprint="0" * 64, state=state,
                    created_at="2026-01-01T00:00:00Z", available_at="2026-01-01T00:00:00Z",
                ))
            session.commit()
        with factory.create_session() as session:
            repository = SqlAlchemyProjectDeletionRepository(session)
            if state == "pending":
                with pytest.raises(ResourceInUseError):
                    repository.delete("project-1")
                session.rollback()
            else:
                repository.delete("project-1")
                session.commit()
        with factory.create_session() as session:
            ids = set(session.scalars(select(QueueOutboxMessageEntity.message_id)))
            assert ids == ({"project-1", "project-2"} if state == "pending" else {"project-2"})
    finally:
        factory.engine.dispose()
