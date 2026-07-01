"""YOLO11 detection PyTorch DataLoader。"""

from __future__ import annotations

import random
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from backend.service.application.models.yolo_core_common.training import (
    YoloInfiniteDataLoader,
    resolve_yolo_dataloader_batch_size,
    resolve_yolo_dataloader_worker_count,
)
from backend.service.application.models.yolo11_core.data.detection import (
    Yolo11DetectionPreparedTarget,
    Yolo11DetectionTrainingSample,
    build_yolo11_detection_training_batch_cpu,
)


@dataclass(frozen=True)
class Yolo11DetectionDataLoaderBatch:
    """描述 DataLoader 返回的 YOLO11 detection CPU batch。"""

    images: Any
    targets: tuple[Yolo11DetectionPreparedTarget, ...]
    input_size: tuple[int, int]

    def pin_memory(self) -> "Yolo11DetectionDataLoaderBatch":
        """让 PyTorch DataLoader 能对自定义 batch 执行 pinned memory。"""

        pin_memory = getattr(self.images, "pin_memory", None)
        if not callable(pin_memory):
            return self
        return Yolo11DetectionDataLoaderBatch(
            images=pin_memory(),
            targets=self.targets,
            input_size=self.input_size,
        )


class Yolo11DetectionTrainingDataset:
    """YOLO11 detection 训练样本 Dataset。"""

    def __init__(self, samples: tuple[Yolo11DetectionTrainingSample, ...]) -> None:
        self._samples = tuple(samples)

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> Yolo11DetectionTrainingSample:
        return self._samples[int(index)]


@dataclass(frozen=True)
class Yolo11DetectionBatchCollator:
    """YOLO11 detection batch collate 逻辑。"""

    input_size: tuple[int, int]
    augment_training: bool
    available_samples: tuple[Yolo11DetectionTrainingSample, ...]
    augmentation_options: Any | None

    def __call__(
        self,
        samples: list[Yolo11DetectionTrainingSample],
    ) -> Yolo11DetectionDataLoaderBatch:
        imports = load_yolo11_detection_dataloader_imports()
        batch_input_size = self._resolve_batch_input_size()
        images, targets = build_yolo11_detection_training_batch_cpu(
            imports=imports,
            samples=list(samples),
            input_size=batch_input_size,
            augment_training=self.augment_training,
            available_samples=self.available_samples,
            augmentation_options=self.augmentation_options,
        )
        return Yolo11DetectionDataLoaderBatch(
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
class Yolo11DetectionDataLoaderPlan:
    """描述 YOLO11 detection DataLoader 配置。"""

    num_workers: int
    pin_memory: bool
    prefetch_factor: int
    persistent_workers: bool
    seed: int


def build_yolo11_detection_training_dataloader(
    *,
    torch_module: Any,
    samples: tuple[Yolo11DetectionTrainingSample, ...],
    batch_size: int,
    input_size: tuple[int, int],
    augment_training: bool,
    augmentation_options: Any | None,
    plan: Yolo11DetectionDataLoaderPlan,
    shuffle: bool,
) -> Any:
    """创建 YOLO11 detection PyTorch DataLoader。"""

    dataset = Yolo11DetectionTrainingDataset(samples=tuple(samples))
    generator = torch_module.Generator()
    generator.manual_seed(max(0, int(plan.seed)))
    num_workers = resolve_yolo_dataloader_worker_count(
        torch_module=torch_module,
        requested_workers=plan.num_workers,
    )
    resolved_batch_size = resolve_yolo_dataloader_batch_size(
        dataset_size=len(dataset),
        batch_size=batch_size,
    )
    loader_kwargs: dict[str, Any] = {
        "batch_size": resolved_batch_size,
        "shuffle": bool(shuffle),
        "num_workers": num_workers,
        "collate_fn": Yolo11DetectionBatchCollator(
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
        loader_kwargs["worker_init_fn"] = seed_yolo11_detection_dataloader_worker
        loader_kwargs["persistent_workers"] = bool(plan.persistent_workers)
        loader_kwargs["prefetch_factor"] = max(1, int(plan.prefetch_factor))
    return YoloInfiniteDataLoader(dataset, torch_module=torch_module, **loader_kwargs)


def load_yolo11_detection_dataloader_imports() -> Any:
    """延迟加载 worker 进程需要的图像和张量模块。"""

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415

    return SimpleNamespace(cv2=cv2, np=np, torch=torch)


def seed_yolo11_detection_dataloader_worker(worker_id: int) -> None:
    """初始化 DataLoader worker 的随机种子。"""

    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415

    worker_seed = int(torch.initial_seed() % 2**32)
    random.seed(worker_seed)
    np.random.seed(worker_seed)


__all__ = [
    "Yolo11DetectionDataLoaderBatch",
    "Yolo11DetectionDataLoaderPlan",
    "build_yolo11_detection_training_dataloader",
]
