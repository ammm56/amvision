"""推理线程复用、立即拒绝和在途资源释放边界。"""

import gc
from threading import Event, get_ident
from time import monotonic, sleep
import weakref

from backend.service.application.runtime.deployment.inference_threads import InferenceThreads


def _wait_idle(pool: InferenceThreads) -> None:
    """仅用于测试：等待 handler 的 finally 完成，避免用 sleep 推测完成时间。"""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        with pool._lock:
            if all(slot.job is None for slot in pool._slots):
                return
        sleep(0.001)
    raise AssertionError("inference threads did not release slots")


def test_capacity_rejects_immediately_without_queuing() -> None:
    """两个在途调用占满后第三个请求不执行，也不等前两个完成。"""
    release = Event()
    rejected = Event()
    pool = InferenceThreads(count=2, name="capacity-test")
    try:
        assert pool.try_submit(lambda: release.wait(2))
        assert pool.try_submit(lambda: release.wait(2))
        started = monotonic()
        assert not pool.try_submit(rejected.set)
        assert monotonic() - started < 0.1
        release.set()
        _wait_idle(pool)
        assert not rejected.is_set()
    finally:
        release.set()
        assert pool.close(timeout=2)


def test_completed_requests_reuse_thread_and_release_captured_payload() -> None:
    """大量顺序调用维持相同线程身份，空闲时不保留上一请求的闭包。"""
    class Payload:
        """可弱引用的测试请求正文。"""

    pool = InferenceThreads(count=1, name="reuse-test")
    identities = set()
    try:
        for _ in range(50):
            payload = Payload()
            reference = weakref.ref(payload)
            assert pool.try_submit(lambda value=payload: identities.add(get_ident()))
            del payload
            _wait_idle(pool)
            gc.collect()
            assert reference() is None
        assert len(identities) == 1
    finally:
        assert pool.close(timeout=2)


def test_handler_error_releases_capacity(caplog) -> None:
    """异常不会遗失槽位，之后仍由同一个常驻线程执行。"""
    pool = InferenceThreads(count=1, name="failure-test")
    identities = []
    def fail():
        """模拟业务 handler 以外的控制通道异常。"""
        identities.append(get_ident())
        raise RuntimeError("test transport failure")
    try:
        assert pool.try_submit(fail)
        _wait_idle(pool)
        assert pool.try_submit(lambda: identities.append(get_ident()))
        _wait_idle(pool)
        assert identities[0] == identities[1]
        assert "test transport failure" in caplog.text
    finally:
        assert pool.close(timeout=2)


def test_shutdown_does_not_claim_inflight_job_has_stopped() -> None:
    """停机超时返回 False；不再接收新调用，实际退出后才能释放外部资源。"""
    started, release = Event(), Event()
    pool = InferenceThreads(count=1, name="shutdown-test")
    def run():
        """模拟持有模型或 mmap reader 的调用。"""
        started.set()
        release.wait(2)
    try:
        assert pool.try_submit(run)
        assert started.wait(1)
        assert not pool.close(timeout=0.01)
        assert not pool.try_submit(lambda: None)
    finally:
        release.set()
        assert pool.close(timeout=2)
