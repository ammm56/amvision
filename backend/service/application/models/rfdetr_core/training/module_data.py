"""RF-DETR core 训练处理模块：`training.module_data`。"""

# ruff: noqa: E402

from typing import Any, List, Optional, Tuple

import torch
import torch.utils.data

from backend.service.application.models.rfdetr_core.training.lightning_bootstrap import (
    disable_lightning_model_summary_import,
)

disable_lightning_model_summary_import()

from pytorch_lightning import LightningDataModule
from torch.utils.data import DataLoader

from backend.service.application.models.rfdetr_core._namespace import _namespace_from_configs
from backend.service.application.models.rfdetr_core.config import ModelConfig, TrainConfig
from backend.service.application.models.rfdetr_core.datasets import build_dataset
from backend.service.application.models.rfdetr_core.datasets.aug_config import AUG_CONFIG
from backend.service.application.models.rfdetr_core.utilities.box_ops import box_xyxy_to_cxcywh
from backend.service.application.models.rfdetr_core.utilities.logger import get_logger
from backend.service.application.models.rfdetr_core.utilities.tensors import make_collate_fn

logger = get_logger()

_MIN_TRAIN_BATCHES = 5


def _has_cuda_device() -> bool:
    """执行 `_has_cuda_device`。
    
    返回：
    - 当前函数的执行结果。
    """
    from backend.service.application.models.rfdetr_core.config import DEVICE

    return str(DEVICE).startswith("cuda")


class GradAccumAlignedDataset(torch.utils.data.Dataset):
    """RF-DETR core 类：`GradAccumAlignedDataset`。"""

    def __init__(
        self,
        dataset: torch.utils.data.Dataset,
        effective_batch_size: int,
        world_size: int = 1,
    ) -> None:
        if effective_batch_size < 1:
            raise ValueError(f"effective_batch_size must be >= 1, got {effective_batch_size}")
        if world_size < 1:
            raise ValueError(f"world_size must be >= 1, got {world_size}")

        self._dataset = dataset
        self._dataset_length = len(dataset)  # type: ignore[arg-type]
        pad_unit = effective_batch_size * world_size
        remainder = self._dataset_length % pad_unit
        pad_count = (pad_unit - remainder) % pad_unit
        pad_index_generator = torch.Generator()
        pad_index_generator.manual_seed(0)
        self._pad_indices: list[int] = (
            torch.randint(
                0,
                self._dataset_length,
                (pad_count,),
                generator=pad_index_generator,
            ).tolist()
            if pad_count > 0
            else []
        )
        self._length = self._dataset_length + pad_count

    def __len__(self) -> int:
        """执行 `__len__`。
        
        返回：
        - 当前函数的执行结果。
        """
        return self._length

    def __getitem__(self, idx: int) -> Any:
        """执行 `__getitem__`。
        
        参数：
        - `idx`：传入的 `idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        dataset_idx = idx if idx < self._dataset_length else self._pad_indices[idx - self._dataset_length]
        return self._dataset[dataset_idx]


def _resolve_augmentation_backend(backend: str) -> str:
    """执行 `_resolve_augmentation_backend`。
    
    参数：
    - `backend`：传入的 `backend` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if backend != "auto":
        return backend
    if not _has_cuda_device():
        return "cpu"
    try:
        import kornia.augmentation  # noqa: F401 # type: ignore[import-not-found]

        return "gpu"
    except ImportError:
        return "cpu"


class RFDETRDataModule(LightningDataModule):
    """RF-DETR core 类：`RFDETRDataModule`。"""

    def __init__(self, model_config: ModelConfig, train_config: TrainConfig) -> None:
        super().__init__()
        self.model_config = model_config
        self.train_config = train_config

        block_size = model_config.patch_size * model_config.num_windows
        if block_size <= 0:
            raise ValueError(
                "Computed collate block_size must be > 0, got "
                f"{block_size} from patch_size={model_config.patch_size} "
                f"and num_windows={model_config.num_windows}."
            )
        self._collate_fn = make_collate_fn(
            block_size=block_size,
        )

        self._dataset_train: Optional[torch.utils.data.Dataset] = None
        self._dataset_val: Optional[torch.utils.data.Dataset] = None
        self._dataset_test: Optional[torch.utils.data.Dataset] = None

        self._kornia_pipeline: Any | None = None
        self._kornia_normalize: Any | None = None
        self._kornia_setup_done: bool = False

        self._num_workers: int = self.train_config.num_workers

        from backend.service.application.models.rfdetr_core.config import DEVICE

        accelerator = str(self.train_config.accelerator).lower()
        uses_cuda_accelerator = accelerator in {"auto", "gpu", "cuda"}
        self._pin_memory: bool = (
            (DEVICE == "cuda" and uses_cuda_accelerator)
            if self.train_config.pin_memory is None
            else bool(self.train_config.pin_memory)
        )
        self._persistent_workers: bool = (
            self._num_workers > 0
            if self.train_config.persistent_workers is None
            else bool(self.train_config.persistent_workers)
        )
        if self._num_workers > 0:
            self._prefetch_factor = (
                self.train_config.prefetch_factor if self.train_config.prefetch_factor is not None else 2
            )
        else:
            self._prefetch_factor = None

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def setup(self, stage: str) -> None:
        """执行 `setup`。
        
        参数：
        - `stage`：传入的 `stage` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        resolution = self.model_config.resolution
        ns = _namespace_from_configs(self.model_config, self.train_config)
        if stage == "fit":
            resolved = _resolve_augmentation_backend(self.train_config.augmentation_backend)
            if resolved != self.train_config.augmentation_backend:
                ns.augmentation_backend = resolved
            if self._dataset_train is None:
                self._dataset_train = build_dataset("train", ns, resolution)
            if self._dataset_val is None:
                self._dataset_val = build_dataset("val", ns, resolution)
            if not self._kornia_setup_done:
                self._setup_kornia_pipeline()
                self._kornia_setup_done = True
        elif stage == "validate":
            if self._dataset_val is None:
                self._dataset_val = build_dataset("val", ns, resolution)
        elif stage == "test":
            if self._dataset_test is None:
                split = "test" if self.train_config.dataset_file == "roboflow" else "val"
                self._dataset_test = build_dataset(split, ns, resolution)
        elif stage == "predict":
            if self._dataset_val is None:
                self._dataset_val = build_dataset("val", ns, resolution)

    def train_dataloader(self) -> DataLoader:
        """执行 `train_dataloader`。
        
        返回：
        - 当前函数的执行结果。
        """
        dataset = self._dataset_train
        batch_size = self.train_config.batch_size
        effective_batch_size = batch_size * self.train_config.grad_accum_steps
        num_workers = self._num_workers

        if len(dataset) < effective_batch_size * _MIN_TRAIN_BATCHES:
            logger.info(
                "Training with uniform sampler because dataset is too small: %d < %d",
                len(dataset),
                effective_batch_size * _MIN_TRAIN_BATCHES,
            )
            sampler = torch.utils.data.RandomSampler(
                dataset,
                replacement=True,
                num_samples=effective_batch_size * _MIN_TRAIN_BATCHES,
            )
            return DataLoader(
                dataset,
                batch_size=batch_size,
                sampler=sampler,
                collate_fn=self._collate_fn,
                num_workers=num_workers,
                pin_memory=self._pin_memory,
                persistent_workers=self._persistent_workers,
                prefetch_factor=self._prefetch_factor,
            )

        world_size: int = getattr(self.trainer, "world_size", 1) if self.trainer else 1
        dataset = GradAccumAlignedDataset(dataset, effective_batch_size, world_size)

        return DataLoader(
            dataset,
            batch_size=batch_size,
            shuffle=True,
            drop_last=True,
            collate_fn=self._collate_fn,
            num_workers=num_workers,
            pin_memory=self._pin_memory,
            persistent_workers=self._persistent_workers,
            prefetch_factor=self._prefetch_factor,
        )

    def val_dataloader(self) -> DataLoader:
        """执行 `val_dataloader`。
        
        返回：
        - 当前函数的执行结果。
        """
        return DataLoader(
            self._dataset_val,
            batch_size=self.train_config.batch_size,
            sampler=torch.utils.data.SequentialSampler(self._dataset_val),
            drop_last=False,
            collate_fn=self._collate_fn,
            num_workers=self._num_workers,
            pin_memory=self._pin_memory,
            persistent_workers=self._persistent_workers,
            prefetch_factor=self._prefetch_factor,
        )

    def test_dataloader(self) -> DataLoader:
        """执行 `test_dataloader`。
        
        返回：
        - 当前函数的执行结果。
        """
        return DataLoader(
            self._dataset_test,
            batch_size=self.train_config.batch_size,
            sampler=torch.utils.data.SequentialSampler(self._dataset_test),
            drop_last=False,
            collate_fn=self._collate_fn,
            num_workers=self._num_workers,
            pin_memory=self._pin_memory,
            persistent_workers=self._persistent_workers,
            prefetch_factor=self._prefetch_factor,
        )

    def predict_dataloader(self) -> DataLoader:
        """执行 `predict_dataloader`。
        
        返回：
        - 当前函数的执行结果。
        """
        return DataLoader(
            self._dataset_val,
            batch_size=self.train_config.batch_size,
            sampler=torch.utils.data.SequentialSampler(self._dataset_val),
            drop_last=False,
            collate_fn=self._collate_fn,
            num_workers=self._num_workers,
            pin_memory=self._pin_memory,
            persistent_workers=self._persistent_workers,
            prefetch_factor=self._prefetch_factor,
        )

    def _setup_kornia_pipeline(self) -> None:
        """执行 `_setup_kornia_pipeline`。
        
        返回：
        - 当前函数的执行结果。
        """
        backend = self.train_config.augmentation_backend
        if backend == "cpu":
            return

        if backend == "auto":
            if not _has_cuda_device():
                logger.warning("augmentation_backend='auto': no CUDA, falling back to CPU augmentation")
                return
            try:
                import kornia.augmentation  # type: ignore[import-not-found]
            except ImportError:
                logger.warning("augmentation_backend='auto': kornia not installed, using CPU augmentation")
                return
        elif backend == "gpu":
            if not _has_cuda_device():
                raise RuntimeError("augmentation_backend='gpu' requires a CUDA device")
            try:
                import kornia.augmentation  # noqa: F401 # type: ignore[import-not-found]
            except ImportError as err:
                raise ImportError("GPU augmentation 需要 kornia，请先按本项目 requirements.txt 安装依赖。") from err

        from backend.service.application.models.rfdetr_core.datasets.kornia_transforms import build_kornia_pipeline, build_normalize

        self._kornia_pipeline = build_kornia_pipeline(
            self.train_config.aug_config if self.train_config.aug_config is not None else AUG_CONFIG,
            self.model_config.resolution,
            with_masks=self.model_config.segmentation_head,
        )
        self._kornia_normalize = build_normalize()
        logger.info("Kornia GPU augmentation pipeline built (backend=%s)", backend)

    def on_after_batch_transfer(self, batch: Tuple, dataloader_idx: int) -> Tuple:
        """执行 `on_after_batch_transfer`。
        
        参数：
        - `batch`：传入的 `batch` 参数。
        - `dataloader_idx`：传入的 `dataloader_idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if self.trainer is None or not self.trainer.training or self._kornia_pipeline is None:
            return batch

        from backend.service.application.models.rfdetr_core.datasets.kornia_transforms import collate_boxes, collate_masks, unpack_boxes
        from backend.service.application.models.rfdetr_core.utilities.tensors import NestedTensor

        samples, targets = batch
        img = samples.tensors
        self._kornia_pipeline.to(img.device)
        self._kornia_normalize.to(img.device)
        boxes_padded, valid = collate_boxes(targets, img.device)

        if self.model_config.segmentation_head:
            image_height, image_width = img.shape[-2:]
            masks_padded = collate_masks(
                targets, img.device, n_max=valid.shape[1], image_height=image_height, image_width=image_width
            )
            img_aug, boxes_aug, masks_aug = self._kornia_pipeline(img, boxes_padded, masks_padded)
            img_aug = self._kornia_normalize(img_aug)
            targets = unpack_boxes(boxes_aug, valid, targets, *img_aug.shape[-2:], masks_aug=masks_aug)
        else:
            img_aug, boxes_aug = self._kornia_pipeline(img, boxes_padded)
            img_aug = self._kornia_normalize(img_aug)
            targets = unpack_boxes(boxes_aug, valid, targets, *img_aug.shape[-2:])

        height, width = img_aug.shape[-2:]
        for target in targets:
            boxes = target["boxes"]
            if boxes.numel() == 0:
                continue
            scale = boxes.new_tensor([width, height, width, height])
            target["boxes"] = box_xyxy_to_cxcywh(boxes) / scale
        batch = (NestedTensor(img_aug, samples.mask), targets)
        return batch

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    @property
    def class_names(self) -> Optional[List[str]]:
        """执行 `class_names`。
        
        返回：
        - 当前函数的执行结果。
        """
        for dataset in (self._dataset_train, self._dataset_val):
            if dataset is None:
                continue
            coco = getattr(dataset, "coco", None)
            if coco is not None and hasattr(coco, "cats"):
                return [coco.cats[k]["name"] for k in sorted(coco.cats.keys())]
        return None

    def transfer_batch_to_device(self, batch: Tuple, device: torch.device, dataloader_idx: int) -> Tuple:
        """执行 `transfer_batch_to_device`。
        
        参数：
        - `batch`：传入的 `batch` 参数。
        - `device`：传入的 `device` 参数。
        - `dataloader_idx`：传入的 `dataloader_idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        samples, targets = batch
        non_blocking = device.type == "cuda"
        samples = samples.to(device, non_blocking=non_blocking)
        targets = [{k: v.to(device, non_blocking=non_blocking) for k, v in t.items()} for t in targets]
        return samples, targets


