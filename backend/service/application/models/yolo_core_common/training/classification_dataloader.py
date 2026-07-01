"""普通 YOLO classification DataLoader。"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

from backend.service.application.models.yolo_core_common.data.tensor_transfer import (
    move_yolo_tensor_to_training_device,
)
from backend.service.application.models.yolo_core_common.training.infinite_dataloader import (
    YoloInfiniteDataLoader,
    resolve_yolo_dataloader_batch_size,
    resolve_yolo_dataloader_worker_count,
)


@dataclass(frozen=True)
class YoloClassificationDataLoaderPlan:
    """描述普通 YOLO classification DataLoader 配置。"""

    num_workers: int
    pin_memory: bool
    prefetch_factor: int
    persistent_workers: bool
    seed: int


class YoloClassificationTrainingDataset:
    """普通 YOLO classification 训练样本 Dataset。"""

    def __init__(self, samples: Sequence[Any]) -> None:
        self._samples = tuple(samples)

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> Any:
        return self._samples[int(index)]


@dataclass(frozen=True)
class YoloClassificationBatchCollator:
    """普通 YOLO classification batch collate 逻辑。"""

    input_size: tuple[int, int]
    augmentation_options: Any | None
    build_batch: Callable[..., Any]
    load_imports: Callable[[], Any]

    def __call__(self, samples: list[Any]) -> Any:
        """在 DataLoader worker 中构建 CPU batch。"""

        return self.build_batch(
            samples=samples,
            input_size=self.input_size,
            device="cpu",
            precision="fp32",
            imports=self.load_imports(),
            augmentation_options=self.augmentation_options,
        )


def build_yolo_classification_training_dataloader(
    *,
    torch_module: Any,
    samples: Sequence[Any],
    batch_size: int,
    input_size: tuple[int, int],
    augmentation_options: Any | None,
    plan: YoloClassificationDataLoaderPlan,
    shuffle: bool,
    build_batch: Callable[..., Any],
    load_imports: Callable[[], Any],
) -> Any:
    """创建普通 YOLO classification PyTorch DataLoader。"""

    dataset = YoloClassificationTrainingDataset(samples=samples)
    generator = torch_module.Generator()
    generator.manual_seed(max(0, int(plan.seed)))
    num_workers = resolve_yolo_dataloader_worker_count(
        torch_module=torch_module,
        requested_workers=plan.num_workers,
    )
    loader_kwargs: dict[str, Any] = {
        "batch_size": resolve_yolo_dataloader_batch_size(
            dataset_size=len(dataset),
            batch_size=batch_size,
        ),
        "shuffle": bool(shuffle),
        "num_workers": num_workers,
        "collate_fn": YoloClassificationBatchCollator(
            input_size=input_size,
            augmentation_options=augmentation_options,
            build_batch=build_batch,
            load_imports=load_imports,
        ),
        "pin_memory": bool(plan.pin_memory),
        "drop_last": False,
        "generator": generator,
    }
    if num_workers > 0:
        loader_kwargs["worker_init_fn"] = seed_yolo_classification_dataloader_worker
        loader_kwargs["persistent_workers"] = bool(plan.persistent_workers)
        loader_kwargs["prefetch_factor"] = max(1, int(plan.prefetch_factor))
    return YoloInfiniteDataLoader(dataset, torch_module=torch_module, **loader_kwargs)


def replace_yolo_classification_dataloader_plan_seed(
    *,
    plan: YoloClassificationDataLoaderPlan,
    seed: int,
) -> YoloClassificationDataLoaderPlan:
    """按 epoch 生成新的 DataLoader seed。"""

    return YoloClassificationDataLoaderPlan(
        num_workers=plan.num_workers,
        pin_memory=plan.pin_memory,
        prefetch_factor=plan.prefetch_factor,
        persistent_workers=plan.persistent_workers,
        seed=int(plan.seed) + int(seed),
    )


def resolve_yolo_classification_dataloader_plan(
    *,
    extra_options: dict[str, object],
    device: str,
) -> YoloClassificationDataLoaderPlan:
    """解析普通 YOLO classification DataLoader 参数。"""

    num_workers = max(
        0,
        _read_int_option(extra_options, "num_workers", default=0),
    )
    return YoloClassificationDataLoaderPlan(
        num_workers=num_workers,
        pin_memory=_read_bool_option(
            extra_options,
            "pin_memory",
            default=str(device).startswith("cuda"),
        ),
        prefetch_factor=max(
            1,
            _read_int_option(extra_options, "prefetch_factor", default=4),
        ),
        persistent_workers=_read_bool_option(
            extra_options,
            "persistent_workers",
            default=num_workers > 0,
        ),
        seed=_read_int_option(extra_options, "seed", default=0),
    )


def move_yolo_classification_batch_to_device(
    *,
    batch: Any,
    device: str,
    precision: str,
    torch_module: Any,
) -> Any:
    """把 DataLoader 产出的 CPU batch 移到训练设备。"""

    return replace(
        batch,
        images=move_yolo_tensor_to_training_device(
            batch.images,
            device=device,
            runtime_precision=precision,
        ),
        targets=batch.targets.to(device=device, dtype=torch_module.long),
    )


def _read_int_option(
    extra_options: dict[str, object],
    key: str,
    *,
    default: int,
) -> int:
    """从 extra_options 中读取整数。"""

    value = extra_options.get(key, default)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float | str):
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)
    return int(default)


def _read_bool_option(
    extra_options: dict[str, object],
    key: str,
    *,
    default: bool,
) -> bool:
    """从 extra_options 中读取布尔值。"""

    value = extra_options.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(default)


def load_yolo_classification_dataloader_imports() -> Any:
    """延迟加载 classification DataLoader worker 依赖。"""

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415

    return SimpleNamespace(cv2=cv2, np=np, torch=torch)


def seed_yolo_classification_dataloader_worker(worker_id: int) -> None:
    """初始化 classification DataLoader worker 的随机种子。"""

    del worker_id
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415

    worker_seed = int(torch.initial_seed() % 2**32)
    random.seed(worker_seed)
    np.random.seed(worker_seed)


__all__ = [
    "YoloClassificationDataLoaderPlan",
    "build_yolo_classification_training_dataloader",
    "load_yolo_classification_dataloader_imports",
    "move_yolo_classification_batch_to_device",
    "replace_yolo_classification_dataloader_plan_seed",
    "resolve_yolo_classification_dataloader_plan",
]
