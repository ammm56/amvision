"""轻量 Transactional Outbox dispatcher 与消息构造。"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from uuid import NAMESPACE_URL, uuid4, uuid5

from backend.service.application.errors import PersistenceOperationError
from backend.service.application.ports.queue import (
    QueueBackend,
    normalize_queue_path_component,
)
from backend.service.domain.tasks.outbox_records import QueueOutboxMessage
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

LOGGER = logging.getLogger(__name__)


def build_task_resume_queue_message_id(*, task_id: str, attempt_no: int) -> str:
    """为同一 Task 恢复轮次生成固定长度、确定性的 outbox message id。"""

    if not task_id.strip():
        raise ValueError("task_id 不能为空")
    if attempt_no <= 0:
        raise ValueError("attempt_no 必须大于 0")
    identity = f"task:{task_id}:attempt:{attempt_no}"
    return f"queue-resume-{uuid5(NAMESPACE_URL, identity).hex}"


@dataclass(frozen=True)
class QueueOutboxDispatcherSettings:
    """定义 backend-service 内轻量 dispatcher 的固定运行边界。"""

    enabled: bool = True
    batch_size: int = 32
    poll_interval_seconds: float = 0.2
    lease_seconds: float = 30.0
    retry_base_seconds: float = 0.5
    retry_max_seconds: float = 30.0
    shutdown_timeout_seconds: float = 5.0


def build_queue_outbox_message(
    *,
    message_id: str,
    queue_name: str,
    payload: dict[str, object],
    metadata: dict[str, object] | None = None,
    created_at: str | None = None,
) -> QueueOutboxMessage:
    """构造一条可与 Task/业务记录放在同一 UoW 提交的消息。"""

    try:
        normalized_message_id = normalize_queue_path_component(
            message_id,
            field_name="message_id",
        )
        normalized_queue_name = normalize_queue_path_component(
            queue_name,
            field_name="queue_name",
        )
    except ValueError as error:
        raise PersistenceOperationError(
            "队列 Outbox 消息 id 或队列名不合法",
            details={
                "message_id": message_id,
                "queue_name": queue_name,
            },
        ) from error
    normalized_payload = dict(payload)
    normalized_metadata = dict(metadata or {})
    payload_fingerprint = _json_fingerprint(normalized_payload, field_name="payload")
    _json_fingerprint(normalized_metadata, field_name="metadata")
    timestamp = created_at or _utc_now_iso()
    return QueueOutboxMessage(
        message_id=normalized_message_id,
        queue_name=normalized_queue_name,
        payload=normalized_payload,
        metadata=normalized_metadata,
        payload_fingerprint=payload_fingerprint,
        created_at=timestamp,
        available_at=timestamp,
    )


class QueueOutboxDispatcher:
    """在短数据库事务之间把 Outbox 消息幂等写入 QueueBackend。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        queue_backend: QueueBackend,
        settings: QueueOutboxDispatcherSettings | None = None,
        dispatcher_id: str | None = None,
    ) -> None:
        """初始化 dispatcher；不在构造期间启动线程或访问数据库。"""

        self.session_factory = session_factory
        self.queue_backend = queue_backend
        self.settings = settings or QueueOutboxDispatcherSettings()
        self.dispatcher_id = dispatcher_id or f"outbox-dispatcher-{uuid4().hex}"
        self._lifecycle_lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        """幂等启动后台投递线程。"""

        if not self.settings.enabled:
            return
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(
                target=self._run,
                name="queue-outbox-dispatcher",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """请求停止并有界等待线程退出。"""

        with self._lifecycle_lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None:
            thread.join(timeout=max(0.1, self.settings.shutdown_timeout_seconds))
        with self._lifecycle_lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def dispatch_once(self, *, now: datetime | None = None) -> int:
        """领取一批消息并在事务外投递，返回本轮成功确认数量。"""

        current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        claimed_at = current_time.isoformat()
        lease_expires_at = (
            current_time + timedelta(seconds=max(1.0, self.settings.lease_seconds))
        ).isoformat()
        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            messages = unit_of_work.queue_outbox.claim_available_messages(
                lease_owner=self.dispatcher_id,
                claimed_at=claimed_at,
                lease_expires_at=lease_expires_at,
                limit=max(1, self.settings.batch_size),
            )
            unit_of_work.commit()
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()

        dispatched_count = 0
        for message in messages:
            # stop 只阻止下一轮领取。当前批次已经持有数据库 lease，必须逐条
            # 投递或进入失败释放路径；中途退出会让未处理消息一直等待 lease
            # 到期，造成服务重启和短生命周期测试中的可见任务停顿。
            try:
                self.queue_backend.enqueue(
                    queue_name=message.queue_name,
                    payload=dict(message.payload),
                    metadata=dict(message.metadata),
                    message_id=message.message_id,
                )
            except Exception as error:  # noqa: BLE001 - 失败必须写回 Outbox 重试时间
                self._release_after_failure(
                    message=message,
                    failed_at=current_time,
                    error=error,
                )
                continue
            if self._mark_dispatched(
                message_id=message.message_id,
                dispatched_at=_utc_now_iso(),
            ):
                dispatched_count += 1
        return dispatched_count

    def _run(self) -> None:
        """持续投递；数据库或文件队列暂时故障不会结束服务线程。"""

        poll_seconds = max(0.01, self.settings.poll_interval_seconds)
        while not self._stop_event.is_set():
            try:
                dispatched_count = self.dispatch_once()
            except Exception:  # noqa: BLE001 - dispatcher 必须长期存活并等待恢复
                LOGGER.exception("队列 Outbox 本轮领取失败")
                dispatched_count = 0
            if dispatched_count == 0:
                self._stop_event.wait(timeout=poll_seconds)

    def _mark_dispatched(self, *, message_id: str, dispatched_at: str) -> bool:
        """在独立短事务中确认成功投递。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            updated = unit_of_work.queue_outbox.mark_dispatched(
                message_id=message_id,
                lease_owner=self.dispatcher_id,
                dispatched_at=dispatched_at,
            )
            unit_of_work.commit()
            return updated
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()

    def _release_after_failure(
        self,
        *,
        message: QueueOutboxMessage,
        failed_at: datetime,
        error: Exception,
    ) -> None:
        """按 attempt_count 指数退避；释放失败时由租约到期兜底。"""

        exponent = max(0, min(message.attempt_count - 1, 16))
        delay_seconds = min(
            max(self.settings.retry_base_seconds, 0.1) * (2**exponent),
            max(self.settings.retry_max_seconds, 0.1),
        )
        available_at = (failed_at + timedelta(seconds=delay_seconds)).isoformat()
        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            unit_of_work.queue_outbox.release_for_retry(
                message_id=message.message_id,
                lease_owner=self.dispatcher_id,
                available_at=available_at,
                error_message=str(error) or type(error).__name__,
            )
            unit_of_work.commit()
        except Exception:  # noqa: BLE001 - 原租约到期后仍能自动恢复
            unit_of_work.rollback()
            LOGGER.exception(
                "释放队列 Outbox 消息租约失败: message_id=%s",
                message.message_id,
            )
        finally:
            unit_of_work.close()


def _json_fingerprint(value: dict[str, object], *, field_name: str) -> str:
    """校验 JSON 兼容性并计算稳定 SHA-256。"""

    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise PersistenceOperationError(
            f"队列 Outbox {field_name} 不是合法 JSON",
            details={"error_type": error.__class__.__name__},
        ) from error
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    """返回带时区的 UTC ISO 时间。"""

    return datetime.now(timezone.utc).isoformat()
