"""普通 YOLO 训练 InfiniteDataLoader。"""

from __future__ import annotations

import gc
import os
from collections.abc import Iterator
from typing import Any


_WORKER_JOIN_TIMEOUT_SECONDS = 1.0


def _close_yolo_dataloader_worker_processes(workers: tuple[Any, ...]) -> None:
    """终止残留 worker，并释放父进程持有的 Windows Process 句柄。"""

    for worker in workers:
        try:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=_WORKER_JOIN_TIMEOUT_SECONDS)
            if worker.is_alive():
                kill = getattr(worker, "kill", None)
                if callable(kill):
                    kill()
                    worker.join(timeout=_WORKER_JOIN_TIMEOUT_SECONDS)
            if not worker.is_alive():
                close = getattr(worker, "close", None)
                if callable(close):
                    close()
                    # PyTorch 在 persistent_workers + pin_memory 时会把同一
                    # Process 注册到 atexit。multiprocessing.Process.close()
                    # 已释放 OS handle，但会把 ``_closed`` 设为 True；PyTorch
                    # 的退出回调随后调用 is_alive() 会因此抛 ValueError。
                    # ``_popen is None`` 已能让 is_alive() 正确返回 False，故只
                    # 恢复可查询状态，不重新创建或保留任何进程句柄。
                    if (
                        bool(getattr(worker, "_closed", False))
                        and getattr(worker, "_popen", None) is None
                    ):
                        worker._closed = False
        except (OSError, ValueError):
            # 退出清理不能覆盖训练本身的异常；Process.close 对已关闭句柄也可能
            # 抛 ValueError，因此这里保持幂等。
            continue


class YoloInfiniteDataLoader:
    """复用 worker 的普通 YOLO 训练 DataLoader。

    Ultralytics 训练器使用无限循环 batch sampler 避免每个 epoch 反复重建
    DataLoader worker。这里保持同样的迭代语义，同时仍让各模型 core 自己负责
    Dataset、collate 和增强逻辑。
    """

    def __new__(
        cls,
        *args: Any,
        torch_module: Any,
        **kwargs: Any,
    ) -> Any:
        """按当前 torch 模块创建 DataLoader 子类实例。"""

        data_loader_base = torch_module.utils.data.DataLoader

        class _YoloInfiniteDataLoader(data_loader_base):  # type: ignore[misc, valid-type]
            """绑定当前 torch 模块的 InfiniteDataLoader 实现。"""

            def __init__(self, *loader_args: Any, **loader_kwargs: Any) -> None:
                # 无限 batch sampler 和常驻 iterator 已经保证 worker 跨 epoch
                # 复用。底层 persistent_workers 会在同时启用 pin memory 时再向
                # atexit 注册相同 Process，和本类显式 close 的句柄释放冲突。
                loader_kwargs["persistent_workers"] = False
                super().__init__(*loader_args, **loader_kwargs)
                object.__setattr__(
                    self,
                    "batch_sampler",
                    _YoloRepeatSampler(self.batch_sampler),
                )
                self.iterator = super().__iter__()

            def __len__(self) -> int:
                return len(self.batch_sampler)

            def __iter__(self) -> Iterator[Any]:
                for _ in range(len(self)):
                    yield next(self.iterator)

            def reset(self) -> None:
                """重建底层 iterator，供关闭 mosaic 等训练阶段切换时使用。"""

                self.iterator = self._get_iterator()

            def close(self) -> None:
                """显式停止 persistent workers；可重复调用。"""

                iterator = getattr(self, "iterator", None)
                if iterator is None:
                    return
                object.__setattr__(self, "iterator", None)
                workers = tuple(getattr(iterator, "_workers", None) or ())
                try:
                    shutdown_workers = getattr(iterator, "_shutdown_workers", None)
                    if callable(shutdown_workers):
                        shutdown_workers()
                finally:
                    _close_yolo_dataloader_worker_processes(workers)
                    # Windows multiprocessing 的 Event / Queue 句柄依赖对象
                    # finalizer 释放。训练阶段切换时 iterator 可能形成引用环，
                    # 等待自动 GC 会让多轮训练出现阶梯式句柄增长，因此在低频
                    # close 边界主动完成一次回收。
                    if os.name == "nt":
                        del iterator
                        gc.collect()

            def __del__(self) -> None:
                """释放 DataLoader worker，避免 Windows 下残留子进程。"""

                try:
                    self.close()
                except Exception:
                    pass

        return _YoloInfiniteDataLoader(*args, **kwargs)


class _YoloRepeatSampler:
    """无限重复已有 batch sampler。"""

    def __init__(self, sampler: Any) -> None:
        self.sampler = sampler

    def __len__(self) -> int:
        return len(self.sampler)

    def __iter__(self) -> Iterator[Any]:
        while True:
            yield from iter(self.sampler)


def resolve_yolo_dataloader_batch_size(*, dataset_size: int, batch_size: int) -> int:
    """按 Ultralytics 规则限制 batch size 不超过数据集大小。"""

    resolved_dataset_size = max(1, int(dataset_size))
    return max(1, min(int(batch_size), resolved_dataset_size))


def resolve_yolo_dataloader_worker_count(
    *,
    torch_module: Any,
    requested_workers: int,
) -> int:
    """按本机 CPU 和可见 GPU 数解析 DataLoader worker 数。"""

    requested = max(0, int(requested_workers))
    if requested <= 0:
        return 0
    cuda_module = getattr(torch_module, "cuda", None)
    cuda_available = bool(
        cuda_module is not None
        and callable(getattr(cuda_module, "is_available", None))
        and cuda_module.is_available()
    )
    gpu_count = 1
    if cuda_available and callable(getattr(cuda_module, "device_count", None)):
        gpu_count = max(1, int(cuda_module.device_count()))
    cpu_count = os.cpu_count() or 1
    return max(0, min(cpu_count // gpu_count, requested))


__all__ = [
    "YoloInfiniteDataLoader",
    "resolve_yolo_dataloader_batch_size",
    "resolve_yolo_dataloader_worker_count",
]
