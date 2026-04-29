"""本地文件系统 QueueBackend 实现。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Protocol
from uuid import uuid4

from backend.service.application.errors import PersistenceOperationError


@dataclass(frozen=True)
class QueueMessage:
    """描述一条队列消息。

    字段：
    - queue_name：所属队列名称。
    - task_id：队列任务 id。
    - payload：任务负载。
    - status：当前队列状态。
    - created_at：入队时间。
    - leased_at：被 worker 领取时间。
    - completed_at：处理完成时间。
    - failed_at：处理失败时间。
    - worker_id：当前领取该任务的 worker id。
    - attempt_count：累计处理尝试次数。
    - error_message：失败时的错误消息。
    - metadata：附加元数据。
    """

    queue_name: str
    task_id: str
    payload: dict[str, object] = field(default_factory=dict)
    status: str = "queued"
    created_at: str = ""
    leased_at: str | None = None
    completed_at: str | None = None
    failed_at: str | None = None
    worker_id: str | None = None
    attempt_count: int = 0
    error_message: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class QueueBackend(Protocol):
    """描述最小任务队列后端接口。"""

    def enqueue(
        self,
        *,
        queue_name: str,
        payload: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> QueueMessage:
        """提交一条新任务到队列。

        参数：
        - queue_name：目标队列名称。
        - payload：任务负载。
        - metadata：附加元数据。

        返回：
        - 已持久化的队列消息。
        """

        ...

    def claim_next(self, *, queue_name: str, worker_id: str) -> QueueMessage | None:
        """领取指定队列中的下一条任务。

        参数：
        - queue_name：目标队列名称。
        - worker_id：当前 worker 标识。

        返回：
        - 已领取的队列消息；没有待处理任务时返回 None。
        """

        ...

    def complete(
        self,
        queue_message: QueueMessage,
        *,
        metadata: dict[str, object] | None = None,
    ) -> QueueMessage:
        """把一条已领取任务标记为完成。"""

        ...

    def fail(
        self,
        queue_message: QueueMessage,
        *,
        error_message: str,
        metadata: dict[str, object] | None = None,
    ) -> QueueMessage:
        """把一条已领取任务标记为失败。"""

        ...

    def get_task(self, *, queue_name: str, task_id: str) -> QueueMessage | None:
        """按任务 id 读取队列消息。"""

        ...


@dataclass(frozen=True)
class LocalFileQueueSettings:
    """描述本地文件队列配置。

    字段：
    - root_dir：队列根目录。
    """

    root_dir: str = "./data/queue"


class LocalFileQueueBackend:
    """基于本地文件系统的最小持久化队列。"""

    def __init__(self, settings: LocalFileQueueSettings) -> None:
        """初始化本地文件队列后端。

        参数：
        - settings：队列配置。
        """

        self.settings = settings
        self.root_dir = Path(settings.root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._claim_lock = Lock()

    def enqueue(
        self,
        *,
        queue_name: str,
        payload: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> QueueMessage:
        """提交一条新任务到队列。

        参数：
        - queue_name：目标队列名称。
        - payload：任务负载。
        - metadata：附加元数据。

        返回：
        - 已持久化的队列消息。
        """

        queue_task = QueueMessage(
            queue_name=queue_name,
            task_id=self._next_id("queue-task"),
            payload=dict(payload),
            status="queued",
            created_at=self._now(),
            metadata=dict(metadata or {}),
        )
        self._write_task(queue_task, state_name="pending")
        return queue_task

    def claim_next(self, *, queue_name: str, worker_id: str) -> QueueMessage | None:
        """领取指定队列中的下一条任务。

        参数：
        - queue_name：目标队列名称。
        - worker_id：当前 worker 标识。

        返回：
        - 已领取的队列消息；没有待处理任务时返回 None。
        """

        pending_dir = self._get_state_dir(queue_name, "pending")
        leased_dir = self._get_state_dir(queue_name, "leased")
        with self._claim_lock:
            for task_path in sorted(pending_dir.glob("*.json")):
                leased_path = leased_dir / task_path.name
                try:
                    queue_task = self._read_task(task_path)
                    task_path.replace(leased_path)
                except FileNotFoundError:
                    continue
                leased_task = QueueMessage(
                    queue_name=queue_task.queue_name,
                    task_id=queue_task.task_id,
                    payload=dict(queue_task.payload),
                    status="leased",
                    created_at=queue_task.created_at,
                    leased_at=self._now(),
                    worker_id=worker_id,
                    attempt_count=queue_task.attempt_count + 1,
                    error_message=None,
                    metadata=dict(queue_task.metadata),
                )
                self._overwrite_task_file(leased_path, leased_task)
                return leased_task

        return None

    def complete(
        self,
        queue_message: QueueMessage,
        *,
        metadata: dict[str, object] | None = None,
    ) -> QueueMessage:
        """把一条已领取任务标记为完成。

        参数：
        - queue_message：已领取的队列消息。
        - metadata：附加元数据。

        返回：
        - 已更新为完成态的队列消息。
        """

        completed_task = QueueMessage(
            queue_name=queue_message.queue_name,
            task_id=queue_message.task_id,
            payload=dict(queue_message.payload),
            status="completed",
            created_at=queue_message.created_at,
            leased_at=queue_message.leased_at,
            completed_at=self._now(),
            worker_id=queue_message.worker_id,
            attempt_count=queue_message.attempt_count,
            error_message=None,
            metadata={
                **queue_message.metadata,
                **dict(metadata or {}),
            },
        )
        self._move_task(queue_message, target_state_name="completed", next_task=completed_task)
        return completed_task

    def fail(
        self,
        queue_message: QueueMessage,
        *,
        error_message: str,
        metadata: dict[str, object] | None = None,
    ) -> QueueMessage:
        """把一条已领取任务标记为失败。

        参数：
        - queue_message：已领取的队列消息。
        - error_message：失败消息。
        - metadata：附加元数据。

        返回：
        - 已更新为失败态的队列消息。
        """

        failed_task = QueueMessage(
            queue_name=queue_message.queue_name,
            task_id=queue_message.task_id,
            payload=dict(queue_message.payload),
            status="failed",
            created_at=queue_message.created_at,
            leased_at=queue_message.leased_at,
            failed_at=self._now(),
            worker_id=queue_message.worker_id,
            attempt_count=queue_message.attempt_count,
            error_message=error_message,
            metadata={
                **queue_message.metadata,
                **dict(metadata or {}),
            },
        )
        self._move_task(queue_message, target_state_name="failed", next_task=failed_task)
        return failed_task

    def get_task(self, *, queue_name: str, task_id: str) -> QueueMessage | None:
        """按任务 id 读取队列消息。

        参数：
        - queue_name：目标队列名称。
        - task_id：任务 id。

        返回：
        - 读取到的队列消息；不存在时返回 None。
        """

        for state_name in ("pending", "leased", "completed", "failed"):
            task_path = self._get_state_dir(queue_name, state_name) / f"{task_id}.json"
            if task_path.is_file():
                return self._read_task(task_path)

        return None

    def _move_task(
        self,
        queue_message: QueueMessage,
        *,
        target_state_name: str,
        next_task: QueueMessage,
    ) -> None:
        """把任务文件从 leased 目录移动到目标目录。"""

        source_path = self._get_state_dir(queue_message.queue_name, "leased") / f"{queue_message.task_id}.json"
        target_path = self._get_state_dir(queue_message.queue_name, target_state_name) / f"{queue_message.task_id}.json"
        try:
            if source_path.exists():
                source_path.unlink()
            self._write_task(next_task, state_name=target_state_name)
        except OSError as error:
            raise PersistenceOperationError(
                "更新队列任务状态失败",
                details={
                    "queue_name": queue_message.queue_name,
                    "task_id": queue_message.task_id,
                    "error_type": error.__class__.__name__,
                },
            ) from error

    def _write_task(self, queue_task: QueueMessage, *, state_name: str) -> None:
        """把队列消息写入指定状态目录。"""

        target_path = self._get_state_dir(queue_task.queue_name, state_name) / f"{queue_task.task_id}.json"
        self._write_task_to_path(target_path, queue_task)

    def _overwrite_task_file(self, task_path: Path, queue_task: QueueMessage) -> None:
        """原地覆写已存在的任务文件。"""

        try:
            task_path.write_text(
                json.dumps(self._build_task_payload(queue_task), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as error:
            raise PersistenceOperationError(
                "写入队列任务失败",
                details={
                    "queue_name": queue_task.queue_name,
                    "task_id": queue_task.task_id,
                    "error_type": error.__class__.__name__,
                },
            ) from error

    def _write_task_to_path(self, task_path: Path, queue_task: QueueMessage) -> None:
        """把队列消息原子写入指定路径。"""

        payload = self._build_task_payload(queue_task)
        try:
            task_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = task_path.with_suffix(f"{task_path.suffix}.tmp")
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(task_path)
        except OSError as error:
            raise PersistenceOperationError(
                "写入队列任务失败",
                details={
                    "queue_name": queue_task.queue_name,
                    "task_id": queue_task.task_id,
                    "error_type": error.__class__.__name__,
                },
            ) from error

    def _build_task_payload(self, queue_task: QueueMessage) -> dict[str, object]:
        """构建用于持久化的队列消息载荷。"""

        payload = {
            "queue_name": queue_task.queue_name,
            "task_id": queue_task.task_id,
            "payload": queue_task.payload,
            "status": queue_task.status,
            "created_at": queue_task.created_at,
            "leased_at": queue_task.leased_at,
            "completed_at": queue_task.completed_at,
            "failed_at": queue_task.failed_at,
            "worker_id": queue_task.worker_id,
            "attempt_count": queue_task.attempt_count,
            "error_message": queue_task.error_message,
            "metadata": queue_task.metadata,
        }
        return payload

    def _read_task(self, task_path: Path) -> QueueMessage:
        """从任务文件恢复队列消息。"""

        try:
            payload = json.loads(task_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PersistenceOperationError(
                "读取队列任务失败",
                details={
                    "task_path": str(task_path),
                    "error_type": error.__class__.__name__,
                },
            ) from error

        return QueueMessage(
            queue_name=str(payload.get("queue_name", "")),
            task_id=str(payload.get("task_id", "")),
            payload=dict(payload.get("payload") or {}),
            status=str(payload.get("status", "queued")),
            created_at=str(payload.get("created_at", "")),
            leased_at=self._read_optional_str(payload, "leased_at"),
            completed_at=self._read_optional_str(payload, "completed_at"),
            failed_at=self._read_optional_str(payload, "failed_at"),
            worker_id=self._read_optional_str(payload, "worker_id"),
            attempt_count=int(payload.get("attempt_count", 0) or 0),
            error_message=self._read_optional_str(payload, "error_message"),
            metadata=dict(payload.get("metadata") or {}),
        )

    def _get_state_dir(self, queue_name: str, state_name: str) -> Path:
        """返回指定队列状态目录并确保目录存在。"""

        target_dir = self.root_dir / queue_name / state_name
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir

    def _next_id(self, prefix: str) -> str:
        """生成一个带前缀的新任务 id。"""

        return f"{prefix}-{uuid4().hex[:12]}"

    def _now(self) -> str:
        """返回当前 UTC 时间字符串。"""

        return datetime.now(timezone.utc).isoformat()

    def _read_optional_str(self, payload: dict[str, object], key: str) -> str | None:
        """从 JSON 对象中读取可选字符串字段。"""

        value = payload.get(key)
        if isinstance(value, str):
            return value
        return None