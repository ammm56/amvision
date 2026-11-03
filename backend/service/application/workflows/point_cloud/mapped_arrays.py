"""同机点云的一次运行所有权，保留关闭失败的真实 guard。"""

from contextlib import contextmanager
from threading import RLock
from typing import Iterator, Mapping

import numpy as np

from backend.service.application.workflows.point_cloud.local_array import (
    borrow_cloud_buffer,
)


class MappedCloudArrays:
    """共享同一个已保护映射；不重复 acquire，不接管 Broker lease。"""

    def __init__(self) -> None:
        """先登记进 Scope，再 open，初始化失败也留在同一清理边界。"""
        self._lock = RLock()
        self._guard = None
        self._guard_error = None
        self._context = None
        self._buffer = None
        self._closed = False
        self._borrows = 0

    def open(self, *, acquire_view, **arguments):
        """复用已核验的布局/摘要/预算扫描，保留原始 guard 的强引用。"""
        with self._lock:
            if self._context is not None or self._closed:
                raise RuntimeError("点云映射只能打开一次")
            owner = self

            class TrackedGuard:
                """原 guard 的关闭错误不能被 generator 退出时丢弃。"""

                def __enter__(self):
                    owner._guard = acquire_view()
                    return owner._guard.__enter__()

                def __exit__(self, *error):
                    try:
                        return owner._guard.__exit__(*error)
                    except BaseException as failure:
                        owner._guard_error = failure
                        raise

            self._context = borrow_cloud_buffer(acquire_view=TrackedGuard, **arguments)
            try:
                self._buffer = self._context.__enter__()
            except BaseException:
                if self._guard_error is None:
                    self._guard = None
                    self._closed = True
                raise
            return self._buffer

    @contextmanager
    def borrow(self) -> Iterator[Mapping[str, np.ndarray]]:
        """分支只增加本地借用计数，不增加 Broker pin。"""
        with self._lock:
            if self._closed or self._guard_error is not None or self._buffer is None:
                raise RuntimeError("点云映射不可用")
            self._borrows += 1
            arrays = self._buffer.arrays
        try:
            yield arrays
        finally:
            with self._lock:
                self._borrows -= 1

    def close(self) -> None:
        """借用未退出或 guard 失败时保留 owner；不重试已失败的关闭。"""
        with self._lock:
            if self._closed:
                return
            if self._guard_error is not None:
                raise RuntimeError("点云 guard 未完整关闭") from self._guard_error
            if self._borrows:
                raise RuntimeError("点云仍有活跃借用，禁止提前释放")
            if self._context is not None:
                self._context.__exit__(None, None, None)
            self._buffer = None
            self._guard = None
            self._context = None
            self._closed = True
