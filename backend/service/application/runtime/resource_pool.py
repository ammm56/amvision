"""可由 Process ResourceScope 持有的有界资源池。"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from threading import RLock
from time import monotonic
from typing import Any, Generic, TypeVar


ResourceT = TypeVar("ResourceT")


@dataclass
class _PoolEntry(Generic[ResourceT]):
    """保存池内资源的生命周期和并发状态。"""

    resource: ResourceT
    closer: Callable[[ResourceT], Any]
    last_used_monotonic: float
    lease_count: int = 0
    execution_lock: RLock = field(default_factory=RLock)


class ResourceLease(Generic[ResourceT]):
    """持有一个池资源，并在一次方法调用后自动归还。"""

    def __init__(
        self,
        *,
        pool: BoundedResourcePool[ResourceT],
        key: Hashable,
        entry: _PoolEntry[ResourceT],
    ) -> None:
        self._pool = pool
        self._key = key
        self._entry = entry
        self._released = False
        self._entered = False

    def __enter__(self) -> ResourceT:
        """串行进入当前资源的一次执行。"""

        if self._released:
            raise RuntimeError("ResourceLease 已释放")
        self._entry.execution_lock.acquire()
        self._entered = True
        return self._entry.resource

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """退出执行锁并归还资源。"""

        if self._entered:
            self._entered = False
            self._entry.execution_lock.release()
        self.release()

    def __getattr__(self, name: str) -> object:
        """代理资源方法，并保证调用结束后归还 lease。"""

        attribute = getattr(self._entry.resource, name)
        if not callable(attribute):
            return attribute

        def invoke(*args: object, **kwargs: object) -> object:
            with self as resource:
                return getattr(resource, name)(*args, **kwargs)

        return invoke

    def release(self) -> None:
        """幂等归还当前 lease。"""

        if self._released:
            return
        self._released = True
        self._pool._release(self._key, self._entry)


class BoundedResourcePool(Generic[ResourceT]):
    """使用 LRU、空闲过期和引用计数限制资源数量。"""

    def __init__(self, *, max_entries: int, max_idle_seconds: float) -> None:
        """创建一个有界资源池。"""

        if max_entries <= 0:
            raise ValueError("max_entries 必须大于 0")
        if max_idle_seconds <= 0:
            raise ValueError("max_idle_seconds 必须大于 0")
        self.max_entries = int(max_entries)
        self.max_idle_seconds = float(max_idle_seconds)
        self._lock = RLock()
        self._entries: OrderedDict[Hashable, _PoolEntry[ResourceT]] = OrderedDict()
        self._closed = False

    @property
    def entry_count(self) -> int:
        """返回当前缓存项数量。"""

        with self._lock:
            return len(self._entries)

    def acquire(
        self,
        key: Hashable,
        factory: Callable[[], ResourceT],
        closer: Callable[[ResourceT], Any],
    ) -> ResourceLease[ResourceT]:
        """获取指定 key 的资源 lease。"""

        with self._lock:
            if self._closed:
                raise RuntimeError("BoundedResourcePool 已关闭")
            now = monotonic()
            self._evict_idle(now)
            entry = self._entries.get(key)
            if entry is None:
                self._make_capacity()
                entry = _PoolEntry(
                    resource=factory(),
                    closer=closer,
                    last_used_monotonic=now,
                )
                self._entries[key] = entry
            else:
                self._entries.move_to_end(key)
            entry.lease_count += 1
            entry.last_used_monotonic = now
            return ResourceLease(pool=self, key=key, entry=entry)

    def close(self) -> None:
        """关闭全部未使用资源；在用资源归还时立即关闭。"""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            close_items = [
                (key, entry)
                for key, entry in self._entries.items()
                if entry.lease_count == 0
            ]
            for key, _entry in close_items:
                self._entries.pop(key, None)
        close_errors: list[Exception] = []
        for _key, entry in close_items:
            try:
                entry.closer(entry.resource)
            except Exception as exc:  # pragma: no cover - 由 scope 聚合测试覆盖
                close_errors.append(exc)
        if close_errors:
            error_summary = "; ".join(
                f"{type(error).__name__}: {error}" for error in close_errors
            )
            raise RuntimeError(
                f"BoundedResourcePool 资源关闭失败: {error_summary}"
            )

    def _release(self, key: Hashable, entry: _PoolEntry[ResourceT]) -> None:
        """归还一个 lease，并在池关闭后释放底层资源。"""

        close_entry = False
        with self._lock:
            current = self._entries.get(key)
            if current is not entry:
                return
            entry.lease_count = max(0, entry.lease_count - 1)
            entry.last_used_monotonic = monotonic()
            if self._closed and entry.lease_count == 0:
                self._entries.pop(key, None)
                close_entry = True
            else:
                self._entries.move_to_end(key)
        if close_entry:
            entry.closer(entry.resource)

    def _evict_idle(self, now: float) -> None:
        """淘汰超过空闲期限且未被使用的资源。"""

        expired_keys = [
            key
            for key, entry in self._entries.items()
            if entry.lease_count == 0
            and now - entry.last_used_monotonic >= self.max_idle_seconds
        ]
        for key in expired_keys:
            entry = self._entries.pop(key)
            entry.closer(entry.resource)

    def _make_capacity(self) -> None:
        """按 LRU 淘汰空闲项，为新资源腾出容量。"""

        while len(self._entries) >= self.max_entries:
            evict_key = next(
                (
                    key
                    for key, entry in self._entries.items()
                    if entry.lease_count == 0
                ),
                None,
            )
            if evict_key is None:
                raise RuntimeError("资源池已满且所有资源都在使用")
            entry = self._entries.pop(evict_key)
            entry.closer(entry.resource)


__all__ = ["BoundedResourcePool", "ResourceLease"]
