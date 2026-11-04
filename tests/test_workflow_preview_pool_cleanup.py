"""Preview 池关闭后不依赖解释器退出才释放同步对象。"""

from pathlib import Path
from types import SimpleNamespace
import os
import json
import signal
import subprocess
import sys
from time import monotonic, sleep
import weakref

import pytest

from backend.service.application.workflows.preview.pool import PreviewSessionPool


def _pool():
    """只创建真实池的空闲资源，不启动 Worker 或替代进程实现。"""
    settings = SimpleNamespace(workflow_runtime=SimpleNamespace(preview_worker_count=2))
    return PreviewSessionPool(settings=settings, manager=None)


def semaphore_paths(pool):
    """收集真实 Event 的五个原生 semaphore 名称，仅用于 Linux 探针。"""
    names = []
    for slot in pool._slots:
        event = slot.cancellation
        for primitive in (event._flag, event._cond._lock, event._cond._sleeping_count,
                          event._cond._woken_count, event._cond._wait_semaphore):
            names.append(Path("/dev/shm") / ("sem." + primitive._semlock.name.lstrip("/")))
    return names


def test_closed_pool_releases_idle_event_ownership():
    """服务保留池对象时，close 也必须释放 Event；不调用 gc.collect 掩盖持有。"""
    pool = _pool()
    events = [weakref.ref(slot.cancellation) for slot in pool._slots]
    try:
        pool.close()
        assert all(reference() is None for reference in events)
        pool.close()
    finally:
        pool._slots.clear()


@pytest.mark.skipif(os.name != "posix" or not Path("/dev/shm").is_dir(), reason="Linux named semaphore")
def test_closed_pool_unlinks_its_named_semaphores():
    """只核对本池实际创建的名称，不以整个 /dev/shm 数量或 WSL 重启代替回收。"""
    pool = _pool()
    names = semaphore_paths(pool)
    try:
        assert len(names) == 10 and all(path.exists() for path in names)
        pool.close()
        assert all(not path.exists() for path in names)
    finally:
        pool._slots.clear()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux Uvicorn signal exit")
def test_sigterm_releases_pool_before_interpreter_exit(tmp_path):
    """同一次 Linux 启动内核对 close 前后原生对象，不让 tracker 兜底冒充主动释放。"""
    boot = Path("/proc/sys/kernel/random/boot_id").read_text()
    with (tmp_path / "server.log").open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "tests.integration.preview_pool_shutdown", str(tmp_path)],
            stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = monotonic() + 60
            while not (tmp_path / "ready.json").exists():
                assert process.poll() is None
                assert monotonic() < deadline
                sleep(.05)
            names = json.loads((tmp_path / "ready.json").read_text())
            assert len(names) == 10 and all(Path(name).exists() for name in names)
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=30)
            closed = json.loads((tmp_path / "closed.json").read_text())
            assert closed["remaining"] == [], closed
            assert Path("/proc/sys/kernel/random/boot_id").read_text() == boot
            assert all(not Path(name).exists() for name in names)
            assert "leaked semaphore" not in (tmp_path / "server.log").read_text()
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)


def test_failed_pool_close_retains_resources_for_retry(monkeypatch):
    """停止未确认时不得丢弃所属资源，修复后仍可沿原 close 重试。"""
    pool = _pool()
    events = [weakref.ref(slot.cancellation) for slot in pool._slots]
    original = pool._close_slot

    def fail(_slot):
        raise RuntimeError("owned process not stopped")

    monkeypatch.setattr(pool, "_close_slot", fail)
    with pytest.raises(RuntimeError, match="not stopped"):
        pool.close()
    assert all(reference() is not None for reference in events)
    monkeypatch.setattr(pool, "_close_slot", original)
    try:
        pool.close()
        assert all(reference() is None for reference in events)
    finally:
        pool._slots.clear()
