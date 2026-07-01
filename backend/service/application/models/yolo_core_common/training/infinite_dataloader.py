"""普通 YOLO 训练 InfiniteDataLoader。"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any


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

            def __del__(self) -> None:
                """释放 DataLoader worker，避免 Windows 下残留子进程。"""

                try:
                    iterator = getattr(self, "iterator", None)
                    workers = getattr(iterator, "_workers", None)
                    if not workers:
                        return
                    for worker in workers:
                        if worker.is_alive():
                            worker.terminate()
                    iterator._shutdown_workers()
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
