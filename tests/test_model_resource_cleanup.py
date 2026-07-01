"""模型任务资源释放工具测试。"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from backend.service.application.support.resource_cleanup import (
    release_model_task_resources,
)


class _ClosableResource:
    """记录 close / shutdown 是否被调用的测试资源。"""

    def __init__(self) -> None:
        self.closed = False
        self.shutdown_called = False

    def close(self) -> None:
        self.closed = True

    def shutdown(self) -> None:
        self.shutdown_called = True


class _FailingCloseResource:
    """模拟关闭失败的资源，确保清理不覆盖任务结果。"""

    def close(self) -> None:
        raise RuntimeError("close failed")


def test_release_model_task_resources_closes_known_resources(monkeypatch) -> None:
    """资源对象提供 close / shutdown 时会被显式释放。"""

    resource = _ClosableResource()
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=None))

    release_model_task_resources(resource)

    assert resource.closed is True
    assert resource.shutdown_called is True


def test_release_model_task_resources_runs_cuda_cache_cleanup(monkeypatch) -> None:
    """CUDA 可用时会清理 PyTorch 缓存和 IPC 引用。"""

    calls: list[str] = []
    fake_cuda = SimpleNamespace(
        is_available=lambda: True,
        empty_cache=lambda: calls.append("empty_cache"),
        ipc_collect=lambda: calls.append("ipc_collect"),
    )
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=fake_cuda))

    release_model_task_resources()

    assert calls == ["empty_cache", "ipc_collect"]


def test_release_model_task_resources_ignores_cleanup_errors(monkeypatch) -> None:
    """单个资源关闭失败时仍继续执行后续缓存清理。"""

    calls: list[str] = []
    fake_cuda = SimpleNamespace(
        is_available=lambda: True,
        empty_cache=lambda: calls.append("empty_cache"),
        ipc_collect=lambda: calls.append("ipc_collect"),
    )
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=fake_cuda))

    release_model_task_resources(_FailingCloseResource())

    assert calls == ["empty_cache", "ipc_collect"]
