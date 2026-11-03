"""运行作用域内不可变点属性；通过借用保护关闭顺序。"""

from __future__ import annotations

from contextlib import contextmanager
from threading import RLock
from types import MappingProxyType
from typing import Iterator, Mapping

import numpy as np

from backend.service.application.workflows.point_cloud.budget import (
    CloudArrayReservation,
)


class OwnedCloudArrays:
    """只拥有本次解码的规范数组，不拥有调用方文件或其他运行资源。"""

    def __init__(
        self, arrays: dict[str, np.ndarray], reservation: CloudArrayReservation
    ) -> None:
        """调用者在成功交接后不得保留可写别名。"""
        for value in arrays.values():
            value.setflags(write=False)
        self._arrays = dict(arrays)
        self._reservation = reservation
        self._lock = RLock()
        self._borrows = 0
        self._closed = False

    @property
    def closed(self) -> bool:
        """是否已解除数组持有。"""
        with self._lock:
            return self._closed

    @contextmanager
    def borrow(self) -> Iterator[Mapping[str, np.ndarray]]:
        """显式借用只读数组；消费者不得将数组保存到作用域之外。"""
        with self._lock:
            if self._closed:
                raise RuntimeError("点云数组已释放")
            self._borrows += 1
            arrays = MappingProxyType(self._arrays)
        try:
            yield arrays
        finally:
            with self._lock:
                self._borrows -= 1

    def close(self) -> None:
        """活跃借用时拒绝提前释放；错误由既有 Scope 上报。"""
        with self._lock:
            if self._closed:
                return
            if self._borrows:
                raise RuntimeError("点云仍有活跃借用，禁止提前释放")
            self._arrays.clear()
            self._reservation.close()
            self._closed = True
