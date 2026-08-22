"""任务队列稳定应用端口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Protocol


@dataclass(frozen=True)
class QueueMessage:
    """描述一条与具体队列实现无关的消息快照。"""

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
    """定义应用层依赖的最小持久队列接口。"""

    def enqueue(
        self,
        *,
        queue_name: str,
        payload: dict[str, object],
        metadata: dict[str, object] | None = None,
        message_id: str | None = None,
    ) -> QueueMessage:
        """提交消息；message_id 用于 Transactional Outbox 幂等投递。"""

        ...

    def claim_next(self, *, queue_name: str, worker_id: str) -> QueueMessage | None:
        """领取指定队列中的下一条消息。"""

        ...

    def refresh_lease(
        self,
        queue_message: QueueMessage,
        *,
        metadata: dict[str, object] | None = None,
    ) -> QueueMessage:
        """刷新当前 worker 持有的消息 lease。"""

        ...

    def complete(
        self,
        queue_message: QueueMessage,
        *,
        metadata: dict[str, object] | None = None,
    ) -> QueueMessage:
        """把已领取消息推进到完成态。"""

        ...

    def fail(
        self,
        queue_message: QueueMessage,
        *,
        error_message: str,
        metadata: dict[str, object] | None = None,
    ) -> QueueMessage:
        """把已领取消息推进到失败态。"""

        ...

    def get_task(self, *, queue_name: str, task_id: str) -> QueueMessage | None:
        """按消息 id 读取队列记录。"""

        ...

    def delete_queue(self, *, queue_name: str) -> bool:
        """删除指定队列。"""

        ...

    def list_tasks_by_references(
        self,
        *,
        references: tuple[tuple[str, object], ...],
    ) -> tuple[QueueMessage, ...]:
        """列出 metadata 或 payload 中匹配任一引用的消息。"""

        ...

    def delete_tasks_by_references(
        self,
        *,
        references: tuple[tuple[str, object], ...],
        statuses: tuple[str, ...],
    ) -> int:
        """删除匹配引用与状态的消息。"""

        ...


def normalize_queue_path_component(value: str, *, field_name: str) -> str:
    """校验 QueueBackend 可安全用作单级目录或文件名的公开标识。"""

    normalized_value = value.strip()
    windows_device_name = normalized_value.split(".", maxsplit=1)[0].upper()
    windows_device_names = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
    if (
        not normalized_value
        or len(normalized_value) > 128
        or normalized_value.endswith((".", " "))
        or normalized_value in {".", ".."}
        or windows_device_name in windows_device_names
        or PurePath(normalized_value).name != normalized_value
        or "/" in normalized_value
        or "\\" in normalized_value
        or any(
            ord(character) < 32 or character in '<>:"|?*'
            for character in normalized_value
        )
    ):
        raise ValueError(f"{field_name} 不是合法的队列路径组件")
    return normalized_value


__all__ = ["QueueBackend", "QueueMessage", "normalize_queue_path_component"]
