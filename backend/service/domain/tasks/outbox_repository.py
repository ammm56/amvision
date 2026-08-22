"""任务队列 Transactional Outbox 仓储协议。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.tasks.outbox_records import QueueOutboxMessage


class QueueOutboxRepository(Protocol):
    """定义 Outbox 写入、租约领取和投递终态的持久化边界。"""

    def add_message(self, message: QueueOutboxMessage) -> None:
        """在当前业务事务中新增一条待投递消息。"""

        ...

    def get_message(self, message_id: str) -> QueueOutboxMessage | None:
        """按确定性消息 id 读取 Outbox 记录。"""

        ...

    def claim_available_messages(
        self,
        *,
        lease_owner: str,
        claimed_at: str,
        lease_expires_at: str,
        limit: int,
    ) -> tuple[QueueOutboxMessage, ...]:
        """使用逐行 CAS 领取到期消息，允许多个 API 进程安全竞争。"""

        ...

    def mark_dispatched(
        self,
        *,
        message_id: str,
        lease_owner: str,
        dispatched_at: str,
    ) -> bool:
        """仅由当前租约持有者把消息标记为已投递。"""

        ...

    def release_for_retry(
        self,
        *,
        message_id: str,
        lease_owner: str,
        available_at: str,
        error_message: str,
    ) -> bool:
        """投递失败后释放租约并安排下一次有界退避重试。"""

        ...
