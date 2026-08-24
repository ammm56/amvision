"""训练 Attempt 最近完整 epoch 的内存 checkpoint 协议。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class CompletedEpochCheckpointSnapshot:
    """保存一份可独立恢复、不会随训练继续变化的 checkpoint bytes。"""

    attempt_id: str
    completed_epoch: int
    checkpoint_bytes: bytes
    content_sha256: str

    @classmethod
    def build(
        cls,
        *,
        attempt_id: str,
        completed_epoch: int,
        checkpoint_bytes: bytes,
    ) -> CompletedEpochCheckpointSnapshot:
        """复制并校验 bytes，禁止保存可变 tensor/state_dict 引用。"""

        if not attempt_id.strip():
            raise ValueError("attempt_id 不能为空")
        epoch = int(completed_epoch)
        if epoch < 0:
            raise ValueError("completed_epoch 不能小于 0")
        immutable_bytes = bytes(checkpoint_bytes)
        if not immutable_bytes:
            raise ValueError("checkpoint_bytes 不能为空")
        return cls(
            attempt_id=attempt_id,
            completed_epoch=epoch,
            checkpoint_bytes=immutable_bytes,
            content_sha256=hashlib.sha256(immutable_bytes).hexdigest(),
        )


@dataclass(frozen=True)
class PersistedCompletedEpochCheckpoint:
    """描述同一 Attempt 已验证的持久 checkpoint 引用。"""

    completed_epoch: int
    content_sha256: str
    role: str
    object_key: str


class CompletedEpochCheckpointCoordinator:
    """原子替换唯一内存快照，并按 epoch/content/role 去重持久化。"""

    def __init__(self, *, attempt_id: str) -> None:
        if not attempt_id.strip():
            raise ValueError("attempt_id 不能为空")
        self.attempt_id = attempt_id
        self._current: CompletedEpochCheckpointSnapshot | None = None
        self._persisted: dict[
            tuple[int, str, str], PersistedCompletedEpochCheckpoint
        ] = {}

    @property
    def current(self) -> CompletedEpochCheckpointSnapshot:
        """返回最近完整 epoch；尚未建立 baseline 时拒绝继续训练。"""

        if self._current is None:
            raise RuntimeError("尚未建立 completed-epoch checkpoint baseline")
        return self._current

    def replace(
        self,
        *,
        completed_epoch: int,
        checkpoint_bytes: bytes,
    ) -> CompletedEpochCheckpointSnapshot:
        """先在局部构造完整新快照，自检成功后再替换旧快照。"""

        candidate = CompletedEpochCheckpointSnapshot.build(
            attempt_id=self.attempt_id,
            completed_epoch=completed_epoch,
            checkpoint_bytes=checkpoint_bytes,
        )
        if (
            self._current is not None
            and candidate.completed_epoch < self._current.completed_epoch
        ):
            raise ValueError("completed_epoch 不能回退")
        self._current = candidate
        return candidate

    def persist_or_reuse(
        self,
        *,
        role: str,
        persist: Callable[[CompletedEpochCheckpointSnapshot], str],
    ) -> PersistedCompletedEpochCheckpoint:
        """持久化当前 bytes；同一内容和角色已完成时直接复用。"""

        normalized_role = role.strip()
        if not normalized_role:
            raise ValueError("checkpoint role 不能为空")
        snapshot = self.current
        identity = (
            snapshot.completed_epoch,
            snapshot.content_sha256,
            normalized_role,
        )
        existing = self._persisted.get(identity)
        if existing is not None:
            return existing
        object_key = persist(snapshot)
        if not isinstance(object_key, str) or not object_key.strip():
            raise RuntimeError("checkpoint 持久化未返回有效 object key")
        persisted = PersistedCompletedEpochCheckpoint(
            completed_epoch=snapshot.completed_epoch,
            content_sha256=snapshot.content_sha256,
            role=normalized_role,
            object_key=object_key.strip(),
        )
        self._persisted[identity] = persisted
        return persisted


__all__ = [
    "CompletedEpochCheckpointCoordinator",
    "CompletedEpochCheckpointSnapshot",
    "PersistedCompletedEpochCheckpoint",
]
