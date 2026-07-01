"""模型任务资源释放工具。"""

from __future__ import annotations

import gc
from collections.abc import Iterator
from contextlib import contextmanager


def _call_if_available(resource: object, method_name: str) -> None:
    """调用资源对象上的关闭方法，关闭失败不覆盖原任务结果。"""

    method = getattr(resource, method_name, None)
    if callable(method):
        try:
            method()
        except Exception:
            pass


def release_model_task_resources(*resources: object) -> None:
    """释放训练、转换任务结束后容易残留的本地和 GPU 资源。"""

    for resource in resources:
        if resource is None:
            continue
        _call_if_available(resource, "close")
        _call_if_available(resource, "shutdown")

    gc.collect()
    try:
        import torch
    except Exception:
        return

    cuda_module = getattr(torch, "cuda", None)
    cuda_available = bool(
        cuda_module is not None
        and callable(getattr(cuda_module, "is_available", None))
        and cuda_module.is_available()
    )
    if not cuda_available:
        return

    # 任务边界只做缓存和进程间引用清理，不改变模型计算逻辑。
    for method_name in ("empty_cache", "ipc_collect"):
        method = getattr(cuda_module, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                pass


@contextmanager
def model_task_resource_cleanup(*resources: object) -> Iterator[None]:
    """在模型任务退出时执行统一资源释放。"""

    try:
        yield
    finally:
        release_model_task_resources(*resources)


__all__ = [
    "model_task_resource_cleanup",
    "release_model_task_resources",
]
