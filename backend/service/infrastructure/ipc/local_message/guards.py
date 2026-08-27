"""LocalMessage 使用的 owner 与 byte-range guard 边界。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from backend.service.infrastructure.ipc.mmap_primitives import (
    MmapGuardBusyError,
    acquire_mmap_guard,
    acquire_mmap_owner_lock,
    release_mmap_owner_lock,
)


_MAX_DESCRIPTOR_GUARD_POLL_SECONDS = 0.0002


def acquire_owner(lock_path: str | Path) -> BinaryIO:
    """取得由 OS 在进程退出时回收的单 owner lock。"""

    return acquire_mmap_owner_lock(lock_path)


def release_owner(handle: BinaryIO) -> None:
    """释放 owner lock。"""

    release_mmap_owner_lock(handle)


@contextmanager
def descriptor_guard(
    *,
    guard_path: str | Path,
    descriptor_index: int,
    deadline_ns: int,
    poll_interval_seconds: float,
) -> Iterator[None]:
    """取得一个 descriptor 对应的固定 byte-range guard。

    Channel profile 的 poll 是空闲消息观察策略；guard 持有时间极短，
    争用重试单独限制为 0.2 ms，避免高并发下将 1 ms 观察周期
    放大到每个 descriptor 状态转移。
    """

    with acquire_mmap_guard(
        guard_path=guard_path,
        deadline_ns=deadline_ns,
        poll_interval_seconds=min(
            poll_interval_seconds,
            _MAX_DESCRIPTOR_GUARD_POLL_SECONDS,
        ),
        offset=descriptor_index,
        length=1,
    ):
        yield


__all__ = [
    "MmapGuardBusyError",
    "acquire_owner",
    "descriptor_guard",
    "release_owner",
]
