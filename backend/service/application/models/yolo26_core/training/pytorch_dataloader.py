"""YOLO26 detection PyTorch DataLoader。"""

from __future__ import annotations

import random
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from backend.service.application.models.yolo26_core.data.detection import (
    Yolo26DetectionPreparedTarget,
    Yolo26DetectionTrainingSample,
    build_yolo26_detection_training_batch_cpu,
)


@dataclass(frozen=True)
class Yolo26DetectionDataLoaderBatch:
    """描述 DataLoader 返回的 YOLO26 detection CPU batch。"""

    images: Any
    targets: tuple[Yolo26DetectionPreparedTarget, ...]
    input_size: tuple[int, int]

    def pin_memory(self) -> "Yolo26DetectionDataLoaderBatch":
        """让 PyTorch DataLoader 能对自定义 batch 执行 pinned memory。"""

        pin_memory = getattr(self.images, "pin_memory", None)
        if not callable(pin_memory):
            return self
        return Yolo26DetectionDataLoaderBatch(
            images=pin_memory(),
            targets=self.targets,
            input_size=self.input_size,
        )


class Yolo26DetectionTrainingDataset:
    """YOLO26 detection 训练样本 Dataset。"""

    def __init__(self, samples: tuple[Yolo26DetectionTrainingSample, ...]) -> None:
        self._samples = tuple(samples)

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> Yolo26DetectionTrainingSample:
        return self._samples[int(index)]


@dataclass(frozen=True)
class Yolo26DetectionBatchCollator:
    """YOLO26 detection batch collate 逻辑。"""

    input_size: tuple[int, int]
    augment_training: bool
    available_samples: tuple[Yolo26DetectionTrainingSample, ...]
    augmentation_options: Any | None

    def __call__(
        self,
        samples: list[Yolo26DetectionTrainingSample],
    ) -> Yolo26DetectionDataLoaderBatch:
        imports = load_yolo26_detection_dataloader_imports()
        batch_input_size = self._resolve_batch_input_size()
        images, targets = build_yolo26_detection_training_batch_cpu(
            imports=imports,
            samples=list(samples),
            input_size=batch_input_size,
            augment_training=self.augment_training,
            available_samples=self.available_samples,
            augmentation_options=self.augmentation_options,
        )
        return Yolo26DetectionDataLoaderBatch(
            images=images,
            targets=targets,
            input_size=batch_input_size,
        )

    def _resolve_batch_input_size(self) -> tuple[int, int]:
        """按增强配置解析当前 batch 的输入尺寸。"""

        options = self.augmentation_options
        if options is None or not options.multi_scale:
            return self.input_size
        min_ratio, max_ratio = options.multi_scale_range
        ratio = random.uniform(float(min_ratio), float(max_ratio))
        stride = max(1, int(options.multi_scale_stride))
        height = max(stride, int(round(self.input_size[0] * ratio / stride)) * stride)
        width = max(stride, int(round(self.input_size[1] * ratio / stride)) * stride)
        return (height, width)


@dataclass(frozen=True)
class Yolo26DetectionDataLoaderPlan:
    """描述 YOLO26 detection DataLoader 配置。"""

    num_workers: int
    pin_memory: bool
    prefetch_factor: int
    persistent_workers: bool
    seed: int


def build_yolo26_detection_training_dataloader(
    *,
    torch_module: Any,
    samples: tuple[Yolo26DetectionTrainingSample, ...],
    batch_size: int,
    input_size: tuple[int, int],
    augment_training: bool,
    augmentation_options: Any | None,
    plan: Yolo26DetectionDataLoaderPlan,
    shuffle: bool,
) -> Any:
    """创建 YOLO26 detection PyTorch DataLoader。"""

    dataset = Yolo26DetectionTrainingDataset(samples=tuple(samples))
    generator = torch_module.Generator()
    generator.manual_seed(max(0, int(plan.seed)))
    num_workers = max(0, int(plan.num_workers))
    loader_kwargs: dict[str, Any] = {
        "batch_size": max(1, int(batch_size)),
        "shuffle": bool(shuffle),
        "num_workers": num_workers,
        "collate_fn": Yolo26DetectionBatchCollator(
            input_size=input_size,
            augment_training=augment_training,
            available_samples=tuple(samples),
            augmentation_options=augmentation_options,
        ),
        "pin_memory": bool(plan.pin_memory),
        "drop_last": False,
        "generator": generator,
    }
    if num_workers > 0:
        loader_kwargs["worker_init_fn"] = seed_yolo26_detection_dataloader_worker
        loader_kwargs["persistent_workers"] = bool(plan.persistent_workers)
        loader_kwargs["prefetch_factor"] = max(1, int(plan.prefetch_factor))
    return torch_module.utils.data.DataLoader(dataset, **loader_kwargs)


def load_yolo26_detection_dataloader_imports() -> Any:
    """延迟加载 worker 进程需要的图像和张量模块。"""

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415

    return SimpleNamespace(cv2=cv2, np=np, torch=torch)


def seed_yolo26_detection_dataloader_worker(worker_id: int) -> None:
    """初始化 DataLoader worker 的随机种子。"""

    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415

    worker_seed = int(torch.initial_seed() % 2**32)
    random.seed(worker_seed)
    np.random.seed(worker_seed)


__all__ = [
    "Yolo26DetectionDataLoaderBatch",
    "Yolo26DetectionDataLoaderPlan",
    "build_yolo26_detection_training_dataloader",
]
