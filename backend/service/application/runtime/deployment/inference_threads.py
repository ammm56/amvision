"""固定数量的推理线程：只向空闲槽交接请求，不维护等待队列。"""

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
from threading import Event, Lock, Thread
from time import monotonic


@dataclass
class _Slot:
    """一个常驻线程的单次交接槽；job 非空即占用，不能覆盖。"""

    wake: Event = field(default_factory=Event)
    job: Callable[[], None] | None = None
    thread: Thread | None = None


class InferenceThreads:
    """复用有界线程和库的线程局部状态；满载立即返回 False。"""

    def __init__(self, *, count: int, name: str) -> None:
        """count 对应部署实例数，name 用于线程诊断。"""
        if count < 1:
            raise ValueError("inference thread count must be positive")
        self._lock = Lock()
        self._closed = False
        self._slots = [_Slot() for _ in range(count)]
        try:
            for index, slot in enumerate(self._slots):
                slot.thread = Thread(
                    target=self._run, args=(slot,), name=f"{name}-{index}", daemon=True
                )
                slot.thread.start()
        except BaseException:
            self.close(timeout=1.0)
            raise

    def try_submit(self, job: Callable[[], None]) -> bool:
        """只占用空闲线程；不等待容量、不缓存后续请求、不重试。"""
        with self._lock:
            if self._closed:
                return False
            for slot in self._slots:
                if slot.job is None and slot.thread is not None and slot.thread.is_alive():
                    slot.job = job
                    slot.wake.set()
                    return True
        return False

    def close(self, *, timeout: float) -> bool:
        """停止接收新请求，限时等待在途调用退出；超时不释放其模型或 mmap。"""
        with self._lock:
            self._closed = True
            for slot in self._slots:
                slot.wake.set()
        deadline = monotonic() + max(0.0, timeout)
        for slot in self._slots:
            if slot.thread is not None and slot.thread.ident is not None:
                slot.thread.join(max(0.0, deadline - monotonic()))
        return all(slot.thread is None or not slot.thread.is_alive() for slot in self._slots)

    def _run(self, slot: _Slot) -> None:
        """执行已接收请求，并在空闲前清除闭包与请求正文的所有槽内引用。"""
        while True:
            slot.wake.wait()
            with self._lock:
                slot.wake.clear()
                job = slot.job
                if job is None and self._closed:
                    return
            if job is None:
                continue
            try:
                job()
            except Exception:
                # 业务 handler 自行返回错误；此处记录控制通道等非预期异常。
                logging.getLogger(__name__).exception("deployment inference handler failed")
            finally:
                job = None
                with self._lock:
                    slot.job = None
                    if self._closed:
                        return
