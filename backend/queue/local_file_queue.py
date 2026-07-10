"""本地文件系统 QueueBackend 实现。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from time import time
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

    def delete_queue(self, *, queue_name: str) -> bool:
        """删除指定队列目录。"""

        ...


@dataclass(frozen=True)
class LocalFileQueueSettings:
    """描述本地文件队列配置。

    字段：
    - root_dir：队列根目录。
    - lease_timeout_seconds：leased 任务超过该秒数未刷新时允许恢复到 pending。
    - completed_retention_seconds：completed 任务文件保留秒数。
    - failed_retention_seconds：failed 任务文件保留秒数。
    - response_queue_retention_seconds：一次性响应队列目录保留秒数。
    """

    root_dir: str = "./data/queue"
    lease_timeout_seconds: float = 86400.0
    completed_retention_seconds: float = 86400.0
    failed_retention_seconds: float = 604800.0
    response_queue_retention_seconds: float = 3600.0


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

        self.recover_expired_leases(queue_name=queue_name)
        pending_dir = self._get_state_dir(queue_name, "pending")
        leased_dir = self._get_state_dir(queue_name, "leased")
        with self._claim_lock:
            for task_path in sorted(pending_dir.glob("*.json")):
                leased_path = leased_dir / task_path.name
                try:
                    task_path.replace(leased_path)
                except FileNotFoundError:
                    continue
                except PermissionError:
                    continue
                try:
                    queue_task = self._read_task(leased_path)
                except PersistenceOperationError:
                    try:
                        leased_path.replace(task_path)
                    except OSError:
                        pass
                    raise
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

    def recover_expired_leases(
        self,
        *,
        queue_name: str,
        lease_timeout_seconds: float | None = None,
    ) -> int:
        """把超时 leased 任务恢复到 pending。

        参数：
        - queue_name：目标队列名称。
        - lease_timeout_seconds：本次恢复使用的 lease 超时秒数；为空时使用队列默认配置。

        返回：
        - int：本次恢复的任务数量。
        """

        timeout_seconds = max(0.1, float(lease_timeout_seconds or self.settings.lease_timeout_seconds))
        leased_dir = self._get_state_dir(queue_name, "leased")
        pending_dir = self._get_state_dir(queue_name, "pending")
        recovered_count = 0
        with self._claim_lock:
            for task_path in sorted(leased_dir.glob("*.json")):
                try:
                    queue_task = self._read_task(task_path)
                except PersistenceOperationError:
                    continue
                if not self._is_lease_expired(queue_task, timeout_seconds=timeout_seconds):
                    continue
                pending_path = pending_dir / task_path.name
                recovered_task = self._build_recovered_task(queue_task)
                try:
                    if pending_path.exists():
                        task_path.unlink(missing_ok=True)
                        continue
                    task_path.replace(pending_path)
                    self._overwrite_task_file(pending_path, recovered_task)
                    recovered_count += 1
                except OSError as error:
                    raise PersistenceOperationError(
                        "恢复超时队列 lease 失败",
                        details={
                            "queue_name": queue_name,
                            "task_id": queue_task.task_id,
                            "error_type": error.__class__.__name__,
                        },
                    ) from error
        return recovered_count

    def refresh_lease(
        self,
        queue_message: QueueMessage,
        *,
        metadata: dict[str, object] | None = None,
    ) -> QueueMessage:
        """刷新已领取任务的 lease 时间。

        参数：
        - queue_message：已领取的队列消息。
        - metadata：需要合并写回的附加元数据。

        返回：
        - QueueMessage：刷新 lease 后的队列消息。
        """

        refreshed_task = QueueMessage(
            queue_name=queue_message.queue_name,
            task_id=queue_message.task_id,
            payload=dict(queue_message.payload),
            status="leased",
            created_at=queue_message.created_at,
            leased_at=self._now(),
            worker_id=queue_message.worker_id,
            attempt_count=queue_message.attempt_count,
            error_message=None,
            metadata={
                **queue_message.metadata,
                **dict(metadata or {}),
            },
        )
        task_path = self._get_state_dir(queue_message.queue_name, "leased") / f"{queue_message.task_id}.json"
        self._assert_current_lease(task_path=task_path, queue_message=queue_message)
        self._overwrite_task_file(task_path, refreshed_task)
        return refreshed_task

    def cleanup_queue(
        self,
        *,
        queue_name: str,
        completed_retention_seconds: float | None = None,
        failed_retention_seconds: float | None = None,
    ) -> dict[str, int]:
        """清理指定队列中超过保留期的终态任务文件。

        参数：
        - queue_name：目标队列名称。
        - completed_retention_seconds：completed 文件保留秒数；为空时使用默认配置。
        - failed_retention_seconds：failed 文件保留秒数；为空时使用默认配置。

        返回：
        - dict[str, int]：按状态统计的删除数量。
        """

        completed_deleted = self._cleanup_state_dir(
            queue_name=queue_name,
            state_name="completed",
            retention_seconds=float(completed_retention_seconds or self.settings.completed_retention_seconds),
        )
        failed_deleted = self._cleanup_state_dir(
            queue_name=queue_name,
            state_name="failed",
            retention_seconds=float(failed_retention_seconds or self.settings.failed_retention_seconds),
        )
        return {"completed": completed_deleted, "failed": failed_deleted}

    def cleanup_queues_by_prefix(
        self,
        *,
        queue_name_prefix: str,
        retention_seconds: float | None = None,
    ) -> int:
        """按队列名前缀清理超过保留期的一次性队列目录。

        参数：
        - queue_name_prefix：需要匹配的队列名前缀。
        - retention_seconds：目录保留秒数；为空时使用响应队列默认配置。

        返回：
        - int：本次删除的队列目录数量。
        """

        normalized_prefix = queue_name_prefix.strip()
        if not normalized_prefix:
            return 0
        timeout_seconds = max(0.1, float(retention_seconds or self.settings.response_queue_retention_seconds))
        deleted_count = 0
        for queue_dir in self.root_dir.iterdir() if self.root_dir.exists() else ():
            if not queue_dir.is_dir() or not queue_dir.name.startswith(normalized_prefix):
                continue
            if not self._is_path_tree_expired(queue_dir, retention_seconds=timeout_seconds):
                continue
            try:
                shutil.rmtree(queue_dir)
                deleted_count += 1
            except OSError as error:
                raise PersistenceOperationError(
                    "清理一次性队列目录失败",
                    details={
                        "queue_name": queue_dir.name,
                        "error_type": error.__class__.__name__,
                    },
                ) from error
        return deleted_count

    def delete_queue(self, *, queue_name: str) -> bool:
        """删除指定队列目录。

        参数：
        - queue_name：目标队列名称。

        返回：
        - bool：实际删除目录时返回 True，目录不存在时返回 False。
        """

        normalized_queue_name = queue_name.strip()
        if not normalized_queue_name:
            return False
        root_dir = self.root_dir.resolve()
        queue_dir = (self.root_dir / normalized_queue_name).resolve()
        if queue_dir.parent != root_dir:
            raise PersistenceOperationError(
                "删除队列目录失败",
                details={"queue_name": normalized_queue_name, "reason": "invalid_queue_name"},
            )
        if not queue_dir.exists():
            return False
        if not queue_dir.is_dir():
            raise PersistenceOperationError(
                "删除队列目录失败",
                details={"queue_name": normalized_queue_name, "reason": "not_a_directory"},
            )
        try:
            shutil.rmtree(queue_dir)
        except OSError as error:
            raise PersistenceOperationError(
                "删除队列目录失败",
                details={
                    "queue_name": normalized_queue_name,
                    "error_type": error.__class__.__name__,
                },
            ) from error
        return True

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
            self._assert_current_lease(task_path=source_path, queue_message=queue_message)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.replace(target_path)
            self._overwrite_task_file(target_path, next_task)
        except OSError as error:
            raise PersistenceOperationError(
                "更新队列任务状态失败",
                details={
                    "queue_name": queue_message.queue_name,
                    "task_id": queue_message.task_id,
                    "error_type": error.__class__.__name__,
                },
            ) from error

    def _assert_current_lease(self, *, task_path: Path, queue_message: QueueMessage) -> None:
        """确认当前 leased 文件仍属于传入的队列消息。"""

        if not task_path.is_file():
            raise PersistenceOperationError(
                "队列任务 lease 已失效",
                details={
                    "queue_name": queue_message.queue_name,
                    "task_id": queue_message.task_id,
                },
            )
        current_task = self._read_task(task_path)
        if (
            current_task.worker_id != queue_message.worker_id
            or current_task.leased_at != queue_message.leased_at
            or current_task.attempt_count != queue_message.attempt_count
        ):
            raise PersistenceOperationError(
                "队列任务 lease 已被其他 worker 接管",
                details={
                    "queue_name": queue_message.queue_name,
                    "task_id": queue_message.task_id,
                    "worker_id": queue_message.worker_id,
                    "current_worker_id": current_task.worker_id,
                },
            )

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

    def _build_recovered_task(self, queue_task: QueueMessage) -> QueueMessage:
        """构造恢复到 pending 状态的队列消息。"""

        recovery_count = queue_task.metadata.get("lease_recovery_count")
        if not isinstance(recovery_count, int):
            recovery_count = 0
        return QueueMessage(
            queue_name=queue_task.queue_name,
            task_id=queue_task.task_id,
            payload=dict(queue_task.payload),
            status="queued",
            created_at=queue_task.created_at,
            leased_at=None,
            completed_at=None,
            failed_at=None,
            worker_id=None,
            attempt_count=queue_task.attempt_count,
            error_message=None,
            metadata={
                **queue_task.metadata,
                "lease_recovery_count": recovery_count + 1,
                "last_lease_recovered_at": self._now(),
                "last_lease_worker_id": queue_task.worker_id,
                "last_leased_at": queue_task.leased_at,
            },
        )

    def _is_lease_expired(self, queue_task: QueueMessage, *, timeout_seconds: float) -> bool:
        """判断队列消息的 lease 是否已经超时。"""

        leased_at = self._parse_time(queue_task.leased_at)
        if leased_at is None:
            return True
        return (datetime.now(timezone.utc) - leased_at).total_seconds() >= timeout_seconds

    def _cleanup_state_dir(self, *, queue_name: str, state_name: str, retention_seconds: float) -> int:
        """清理指定状态目录中过期的任务文件。"""

        state_dir = self._get_state_dir(queue_name, state_name)
        deleted_count = 0
        for task_path in sorted(state_dir.glob("*.json")):
            if not self._is_file_expired(task_path, retention_seconds=max(0.1, retention_seconds)):
                continue
            try:
                task_path.unlink()
                deleted_count += 1
            except OSError as error:
                raise PersistenceOperationError(
                    "清理队列任务文件失败",
                    details={
                        "queue_name": queue_name,
                        "state_name": state_name,
                        "task_path": str(task_path),
                        "error_type": error.__class__.__name__,
                    },
                ) from error
        return deleted_count

    def _is_file_expired(self, task_path: Path, *, retention_seconds: float) -> bool:
        """判断任务文件是否已经超过保留期。"""

        try:
            modified_at = task_path.stat().st_mtime
        except OSError:
            return False
        return time() - modified_at >= retention_seconds

    def _is_path_tree_expired(self, path: Path, *, retention_seconds: float) -> bool:
        """判断目录树是否已经超过保留期。"""

        newest_modified_at = path.stat().st_mtime
        for child_path in path.rglob("*"):
            try:
                newest_modified_at = max(newest_modified_at, child_path.stat().st_mtime)
            except OSError:
                continue
        return time() - newest_modified_at >= retention_seconds

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

    def _parse_time(self, value: str | None) -> datetime | None:
        """解析队列文件中的 ISO 时间。"""

        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed_value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed_value.tzinfo is None:
            return parsed_value.replace(tzinfo=timezone.utc)
        return parsed_value.astimezone(timezone.utc)

    def _read_optional_str(self, payload: dict[str, object], key: str) -> str | None:
        """从 JSON 对象中读取可选字符串字段。"""

        value = payload.get(key)
        if isinstance(value, str):
            return value
        return None
