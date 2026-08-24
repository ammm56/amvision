"""持久任务队列消费侧的 TaskAttempt 幂等领取装饰器。"""

from __future__ import annotations

from threading import Lock
from typing import Any

from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
)
from backend.service.application.ports.queue import QueueBackend, QueueMessage
from backend.service.application.tasks.task_service import (
    SqlAlchemyTaskService,
    TaskExecutionFence,
)
from backend.service.domain.tasks.task_records import TaskAttemptState
from backend.service.infrastructure.db.session import SessionFactory


class TaskAttemptClaimingQueueBackend:
    """在持久队列消息进入业务 worker 前原子领取 TaskAttempt。

    该装饰器只用于正式 TaskRecord 驱动的 request 队列。推理 reply/control
    队列仍直接使用底层 QueueBackend，不经过数据库 claim。
    """

    def __init__(
        self,
        *,
        queue_backend: QueueBackend,
        session_factory: SessionFactory,
    ) -> None:
        """初始化装饰器并保留当前进程已领取消息与 Attempt 的对应关系。"""

        self.queue_backend = queue_backend
        self.task_service = SqlAlchemyTaskService(session_factory)
        self._attempt_ids: dict[tuple[str, str, str | None, str | None], str] = {}
        self._attempt_ids_lock = Lock()

    def enqueue(
        self,
        *,
        queue_name: str,
        payload: dict[str, object],
        metadata: dict[str, object] | None = None,
        message_id: str | None = None,
    ) -> QueueMessage:
        """把控制面产生的新消息原样交给底层队列。"""

        return self.queue_backend.enqueue(
            queue_name=queue_name,
            payload=payload,
            metadata=metadata,
            message_id=message_id,
        )

    def claim_next(self, *, queue_name: str, worker_id: str) -> QueueMessage | None:
        """领取下一条未执行消息，并用 TaskAttempt 唯一键取得执行权。"""

        while True:
            queue_message = self.queue_backend.claim_next(
                queue_name=queue_name,
                worker_id=worker_id,
            )
            if queue_message is None:
                return None
            try:
                task_id, attempt_no = self._read_execution_identity(queue_message)
                queue_leased_at = queue_message.leased_at
                if queue_leased_at is None:
                    raise InvalidRequestError(
                        "已领取的持久任务队列消息缺少 leased_at",
                        details={"queue_message_id": queue_message.task_id},
                    )
                claim = self.task_service.claim_task_execution(
                    task_id=task_id,
                    attempt_no=attempt_no,
                    worker_id=worker_id,
                    queue_name=queue_name,
                    queue_message_id=queue_message.task_id,
                    queue_attempt_count=queue_message.attempt_count,
                    queue_leased_at=queue_leased_at,
                    lease_recovery_count=self._read_lease_recovery_count(
                        queue_message
                    ),
                    queue_metadata=queue_message.metadata,
                )
            except (InvalidRequestError, ResourceNotFoundError) as error:
                self.queue_backend.fail(
                    queue_message,
                    error_message=error.message,
                    metadata={
                        "task_execution_claim": "rejected",
                        "error_code": error.code,
                    },
                )
                continue

            if claim.acquired:
                if claim.attempt is None:
                    raise RuntimeError("TaskAttempt claim 成功但缺少 attempt")
                with self._attempt_ids_lock:
                    self._attempt_ids[self._message_key(queue_message)] = (
                        claim.attempt.attempt_id
                    )
                return queue_message

            # 重复投递不再进入业务 service，避免训练、转换或验证副作用重放。
            self.queue_backend.complete(
                queue_message,
                metadata={
                    "task_id": task_id,
                    "attempt_no": attempt_no,
                    "status": "duplicate_suppressed",
                    "task_execution_claim": claim.outcome,
                    "claimed_attempt_id": (
                        claim.attempt.attempt_id if claim.attempt is not None else None
                    ),
                },
            )

    def refresh_lease(
        self,
        queue_message: QueueMessage,
        *,
        metadata: dict[str, object] | None = None,
    ) -> QueueMessage:
        """刷新底层 lease，并同步更新进程内消息与 Attempt 的关联键。"""

        refreshed = self.queue_backend.refresh_lease(
            queue_message,
            metadata=metadata,
        )
        old_key = self._message_key(queue_message)
        with self._attempt_ids_lock:
            attempt_id = self._attempt_ids.pop(old_key, None)
            if attempt_id is not None:
                self._attempt_ids[self._message_key(refreshed)] = attempt_id
        if attempt_id is not None:
            worker_id = refreshed.worker_id
            heartbeat_at = refreshed.leased_at
            if worker_id is None or heartbeat_at is None:
                raise RuntimeError("刷新 queue lease 后缺少 worker_id 或 leased_at")
            if not self.task_service.heartbeat_task_attempt(
                attempt_id=attempt_id,
                worker_id=worker_id,
                heartbeat_at=heartbeat_at,
            ):
                raise RuntimeError("当前 queue lease 已不是 TaskAttempt owner")
        return refreshed

    def get_execution_fence(
        self,
        queue_message: QueueMessage,
        *,
        include_heartbeat: bool = True,
    ) -> TaskExecutionFence:
        """返回当前进程持有的消息与 TaskAttempt 精确执行边界。"""

        with self._attempt_ids_lock:
            attempt_id = self._attempt_ids.get(self._message_key(queue_message))
            if attempt_id is None and not include_heartbeat:
                message_identity = self._message_key(queue_message)[:3]
                attempt_id = next(
                    (
                        mapped_attempt_id
                        for key, mapped_attempt_id in self._attempt_ids.items()
                        if key[:3] == message_identity
                    ),
                    None,
                )
        if attempt_id is None:
            raise RuntimeError("队列消息缺少当前进程持有的 TaskAttempt claim")
        worker_id = queue_message.worker_id
        heartbeat_at = queue_message.leased_at
        if worker_id is None or heartbeat_at is None:
            raise RuntimeError("队列消息缺少 TaskAttempt fence")
        return TaskExecutionFence(
            attempt_id=attempt_id,
            worker_id=worker_id,
            heartbeat_at=heartbeat_at if include_heartbeat else None,
            queue_message_id=queue_message.task_id,
            queue_attempt_count=queue_message.attempt_count,
        )

    def complete(
        self,
        queue_message: QueueMessage,
        *,
        metadata: dict[str, object] | None = None,
    ) -> QueueMessage:
        """先把 TaskAttempt 原子结束，再提交队列完成态。"""

        normalized_metadata = dict(metadata or {})
        attempt_state = self._resolve_completed_attempt_state(normalized_metadata)
        self._finish_attempt(
            queue_message,
            state=attempt_state,
            result={"queue_result": normalized_metadata},
        )
        completed = self.queue_backend.complete(
            queue_message,
            metadata=normalized_metadata,
        )
        self._forget_attempt(queue_message)
        return completed

    def fail(
        self,
        queue_message: QueueMessage,
        *,
        error_message: str,
        metadata: dict[str, object] | None = None,
    ) -> QueueMessage:
        """按失败元数据收敛 Attempt，再提交队列失败态。"""

        normalized_metadata = dict(metadata or {})
        attempt_state = self._resolve_failed_attempt_state(normalized_metadata)
        self._finish_attempt(
            queue_message,
            state=attempt_state,
            result={"queue_result": normalized_metadata},
            error_message=error_message,
        )
        failed = self.queue_backend.fail(
            queue_message,
            error_message=error_message,
            metadata=normalized_metadata,
        )
        self._forget_attempt(queue_message)
        return failed

    def defer_recovery(self, queue_message: QueueMessage) -> None:
        """保留底层 lease 供过期接管，仅释放本进程 Attempt 映射。"""

        self._forget_attempt(queue_message)

    def get_task(self, *, queue_name: str, task_id: str) -> QueueMessage | None:
        """读取底层队列消息。"""

        return self.queue_backend.get_task(queue_name=queue_name, task_id=task_id)

    def delete_queue(self, *, queue_name: str) -> bool:
        """删除底层队列。"""

        return self.queue_backend.delete_queue(queue_name=queue_name)

    def list_tasks_by_references(
        self,
        *,
        references: tuple[tuple[str, object], ...],
    ) -> tuple[QueueMessage, ...]:
        """按引用列出底层队列消息。"""

        return self.queue_backend.list_tasks_by_references(references=references)

    def delete_tasks_by_references(
        self,
        *,
        references: tuple[tuple[str, object], ...],
        statuses: tuple[str, ...],
    ) -> int:
        """按引用删除底层队列消息。"""

        return self.queue_backend.delete_tasks_by_references(
            references=references,
            statuses=statuses,
        )

    def __getattr__(self, name: str) -> Any:
        """代理 QueueBackend 的维护扩展，例如 recover_expired_leases。"""

        return getattr(self.queue_backend, name)

    def _finish_attempt(
        self,
        queue_message: QueueMessage,
        *,
        state: TaskAttemptState,
        result: dict[str, object],
        error_message: str | None = None,
    ) -> None:
        """结束当前消息在 claim 阶段登记的 TaskAttempt。"""

        with self._attempt_ids_lock:
            attempt_id = self._attempt_ids.get(self._message_key(queue_message))
        if attempt_id is None:
            raise RuntimeError(
                "队列消息缺少当前进程持有的 TaskAttempt claim: "
                f"queue={queue_message.queue_name}, message={queue_message.task_id}"
            )
        worker_id = queue_message.worker_id
        heartbeat_at = queue_message.leased_at
        if worker_id is None or heartbeat_at is None:
            raise RuntimeError("队列消息缺少 TaskAttempt finalizer fence")
        finalization = self.task_service.finalize_task_execution_attempt(
            attempt_id=attempt_id,
            attempt_outcome=state,
            result=result,
            error_message=error_message,
            metadata={"queue_attempt_count": queue_message.attempt_count},
            expected_worker_id=worker_id,
            expected_heartbeat_at=heartbeat_at,
            expected_queue_message_id=queue_message.task_id,
            expected_queue_attempt_count=queue_message.attempt_count,
        )
        if finalization.attempt.state == "running":
            raise RuntimeError(
                "当前 queue lease 已失去 TaskAttempt 终态写入权: "
                f"queue={queue_message.queue_name}, message={queue_message.task_id}"
            )

    def _forget_attempt(self, queue_message: QueueMessage) -> None:
        """删除已经提交队列终态的进程内 Attempt 关联。"""

        with self._attempt_ids_lock:
            self._attempt_ids.pop(self._message_key(queue_message), None)

    @staticmethod
    def _read_execution_identity(queue_message: QueueMessage) -> tuple[str, int]:
        """严格读取 Outbox 固化的 task_id 与 attempt_no。"""

        task_id = queue_message.payload.get("task_id")
        attempt_no = queue_message.payload.get("attempt_no")
        if not isinstance(task_id, str) or not task_id.strip():
            raise InvalidRequestError(
                "持久任务队列消息缺少 task_id",
                details={"queue_message_id": queue_message.task_id},
            )
        if (
            isinstance(attempt_no, bool)
            or not isinstance(attempt_no, int)
            or attempt_no <= 0
        ):
            raise InvalidRequestError(
                "持久任务队列消息缺少有效 attempt_no",
                details={
                    "queue_message_id": queue_message.task_id,
                    "attempt_no": attempt_no,
                },
            )
        return task_id.strip(), attempt_no

    @staticmethod
    def _resolve_completed_attempt_state(
        metadata: dict[str, object],
    ) -> TaskAttemptState:
        """把业务完成结果映射为 TaskAttempt 正式终态。"""

        status = metadata.get("status")
        if status == "paused":
            return "paused"
        if status == "cancelled":
            return "cancelled"
        if status == "timed_out":
            return "timed_out"
        if status == "failed":
            return "failed"
        return "succeeded"

    @staticmethod
    def _resolve_failed_attempt_state(
        metadata: dict[str, object],
    ) -> TaskAttemptState:
        """把业务错误类型映射为 TaskAttempt 失败类终态。"""

        status = metadata.get("status")
        if status == "timed_out":
            return "timed_out"
        if status == "cancelled":
            return "cancelled"
        return "failed"

    @staticmethod
    def _read_lease_recovery_count(queue_message: QueueMessage) -> int:
        """读取本地持久队列记录的 lease 恢复次数。"""

        value = queue_message.metadata.get("lease_recovery_count")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return 0
        return value

    @staticmethod
    def _message_key(
        queue_message: QueueMessage,
    ) -> tuple[str, str, str | None, str | None]:
        """构造可区分 lease 刷新的进程内消息键。"""

        return (
            queue_message.queue_name,
            queue_message.task_id,
            queue_message.worker_id,
            queue_message.leased_at,
        )


__all__ = ["TaskAttemptClaimingQueueBackend"]
