"""单次 Workflow 的数组容量记账，分配前准入；容量不足立即拒绝。"""

from __future__ import annotations

from threading import RLock

from backend.service.application.errors import InvalidRequestError


class CloudArrayBudget:
    """运行内共享的活跃数组预算，不是进程 RSS 或调度队列。"""

    def __init__(self, limit: int) -> None:
        """limit 必须来自显式策略。"""
        if type(limit) is not int or limit <= 0:
            raise ValueError("点云数组预算必须是正整数")
        self.limit = limit
        self._used = 0
        self._lock = RLock()

    @property
    def used(self) -> int:
        """当前尚未释放的数组预留字节。"""
        with self._lock:
            return self._used

    def reserve(self, size: int) -> CloudArrayReservation:
        """在真正分配之前登记容量；异常不得改变计费。"""
        if type(size) is not int or size < 0:
            raise ValueError("数组预留字节必须为非负整数")
        with self._lock:
            if size > self.limit - self._used:
                raise InvalidRequestError(
                    "点云活跃数组超过运行预算",
                    details={
                        "requested_bytes": size,
                        "used_bytes": self._used,
                        "limit_bytes": self.limit,
                    },
                )
            self._used += size
            return CloudArrayReservation(self, size)


class CloudArrayReservation:
    """一个已准入分配的所有权；释放幂等，不允许扩大已有预留。"""

    def __init__(self, budget: CloudArrayBudget, size: int) -> None:
        """由 CloudArrayBudget 在锁内创建。"""
        self._budget = budget
        self._size = size
        self._closed = False

    def shrink(self, size: int) -> None:
        """临时解码数组释放后减少计费，不重新准入。"""
        with self._budget._lock:
            if self._closed or type(size) is not int or not 0 <= size <= self._size:
                raise RuntimeError("点云预留已关闭或缩减长度不合法")
            self._budget._used -= self._size - size
            self._size = size

    def close(self) -> None:
        """资源实际解除持有后归还计费。"""
        with self._budget._lock:
            if not self._closed:
                self._budget._used -= self._size
                self._size = 0
                self._closed = True

    def split(self, size: int) -> CloudArrayReservation:
        """同一已准入分配交给独立 owner，不瞬时解除实际占用计费。"""
        with self._budget._lock:
            if self._closed or type(size) is not int or not 0 <= size <= self._size:
                raise RuntimeError("点云预留不能拆分为给定大小")
            self._size -= size
            return CloudArrayReservation(self._budget, size)
