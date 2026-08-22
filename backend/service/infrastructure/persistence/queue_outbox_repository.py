"""SQLAlchemy Transactional Outbox 仓储实现。"""

from __future__ import annotations

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.tasks.outbox_records import QueueOutboxMessage
from backend.service.infrastructure.persistence.queue_outbox_orm import (
    QueueOutboxMessageEntity,
)


class SqlAlchemyQueueOutboxRepository:
    """通过短事务和逐行 CAS 管理 Outbox 消息租约。"""

    def __init__(self, session: Session) -> None:
        """绑定当前 UnitOfWork 持有的 SQLAlchemy Session。"""

        self.session = session

    def add_message(self, message: QueueOutboxMessage) -> None:
        """新增消息；确定性 message_id 冲突由数据库约束拒绝。"""

        try:
            self.session.add(self._to_entity(message))
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "新增队列 Outbox 消息失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_message(self, message_id: str) -> QueueOutboxMessage | None:
        """按 id 读取消息。"""

        try:
            entity = self.session.get(QueueOutboxMessageEntity, message_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取队列 Outbox 消息失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return self._to_domain(entity) if entity is not None else None

    def claim_available_messages(
        self,
        *,
        lease_owner: str,
        claimed_at: str,
        lease_expires_at: str,
        limit: int,
    ) -> tuple[QueueOutboxMessage, ...]:
        """先取候选 id，再以资格条件逐行 CAS，避免多进程重复持有租约。"""

        normalized_limit = max(1, min(int(limit), 1000))
        eligible = self._eligible_expression(claimed_at)
        candidate_statement = (
            select(QueueOutboxMessageEntity.message_id)
            .where(eligible)
            .order_by(
                QueueOutboxMessageEntity.available_at,
                QueueOutboxMessageEntity.created_at,
                QueueOutboxMessageEntity.message_id,
            )
            .limit(normalized_limit)
        )
        try:
            candidate_ids = tuple(self.session.execute(candidate_statement).scalars())
            claimed_ids: list[str] = []
            for message_id in candidate_ids:
                result = self.session.execute(
                    update(QueueOutboxMessageEntity)
                    .where(
                        QueueOutboxMessageEntity.message_id == message_id,
                        self._eligible_expression(claimed_at),
                    )
                    .values(
                        state="leased",
                        lease_owner=lease_owner,
                        lease_expires_at=lease_expires_at,
                        attempt_count=QueueOutboxMessageEntity.attempt_count + 1,
                        last_error=None,
                    )
                    .execution_options(synchronize_session=False)
                )
                if result.rowcount == 1:
                    claimed_ids.append(str(message_id))
            if not claimed_ids:
                return ()
            claimed_entities = (
                self.session.execute(
                    select(QueueOutboxMessageEntity)
                    .where(QueueOutboxMessageEntity.message_id.in_(claimed_ids))
                    .order_by(
                        QueueOutboxMessageEntity.available_at,
                        QueueOutboxMessageEntity.created_at,
                        QueueOutboxMessageEntity.message_id,
                    )
                )
                .scalars()
                .all()
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "领取队列 Outbox 消息失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._to_domain(entity) for entity in claimed_entities)

    def mark_dispatched(
        self,
        *,
        message_id: str,
        lease_owner: str,
        dispatched_at: str,
    ) -> bool:
        """以 message_id + lease_owner CAS 发布投递终态。"""

        try:
            result = self.session.execute(
                update(QueueOutboxMessageEntity)
                .where(
                    QueueOutboxMessageEntity.message_id == message_id,
                    QueueOutboxMessageEntity.state == "leased",
                    QueueOutboxMessageEntity.lease_owner == lease_owner,
                )
                .values(
                    state="dispatched",
                    dispatched_at=dispatched_at,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error=None,
                )
                .execution_options(synchronize_session=False)
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "完成队列 Outbox 投递失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return result.rowcount == 1

    def release_for_retry(
        self,
        *,
        message_id: str,
        lease_owner: str,
        available_at: str,
        error_message: str,
    ) -> bool:
        """仅释放当前持有者的租约，旧 dispatcher 不能覆盖新租约。"""

        try:
            result = self.session.execute(
                update(QueueOutboxMessageEntity)
                .where(
                    QueueOutboxMessageEntity.message_id == message_id,
                    QueueOutboxMessageEntity.state == "leased",
                    QueueOutboxMessageEntity.lease_owner == lease_owner,
                )
                .values(
                    state="pending",
                    available_at=available_at,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error=error_message[:2048],
                )
                .execution_options(synchronize_session=False)
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "释放队列 Outbox 租约失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return result.rowcount == 1

    @staticmethod
    def _eligible_expression(now: str):
        """构造 pending 到期或 leased 租约过期的统一领取条件。"""

        return or_(
            and_(
                QueueOutboxMessageEntity.state == "pending",
                QueueOutboxMessageEntity.available_at <= now,
            ),
            and_(
                QueueOutboxMessageEntity.state == "leased",
                QueueOutboxMessageEntity.lease_expires_at.is_not(None),
                QueueOutboxMessageEntity.lease_expires_at <= now,
            ),
        )

    @staticmethod
    def _to_entity(message: QueueOutboxMessage) -> QueueOutboxMessageEntity:
        """把领域记录转换成 ORM 实体。"""

        return QueueOutboxMessageEntity(
            message_id=message.message_id,
            queue_name=message.queue_name,
            payload_json=dict(message.payload),
            metadata_json=dict(message.metadata),
            payload_fingerprint=message.payload_fingerprint,
            state=message.state,
            created_at=message.created_at,
            available_at=message.available_at,
            lease_owner=message.lease_owner,
            lease_expires_at=message.lease_expires_at,
            dispatched_at=message.dispatched_at,
            attempt_count=message.attempt_count,
            last_error=message.last_error,
        )

    @staticmethod
    def _to_domain(entity: QueueOutboxMessageEntity) -> QueueOutboxMessage:
        """把 ORM 实体转换成领域记录。"""

        return QueueOutboxMessage(
            message_id=entity.message_id,
            queue_name=entity.queue_name,
            payload=dict(entity.payload_json or {}),
            metadata=dict(entity.metadata_json or {}),
            payload_fingerprint=entity.payload_fingerprint,
            state=entity.state,
            created_at=entity.created_at,
            available_at=entity.available_at,
            lease_owner=entity.lease_owner,
            lease_expires_at=entity.lease_expires_at,
            dispatched_at=entity.dispatched_at,
            attempt_count=entity.attempt_count,
            last_error=entity.last_error,
        )
