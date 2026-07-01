"""普通 YOLO 非 detection 任务 DataLoader。"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields, is_dataclass, replace
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
class YoloTaskDataLoaderPlan:
    """描述普通 YOLO task DataLoader 配置。"""

    num_workers: int
    pin_memory: bool
    prefetch_factor: int
    persistent_workers: bool
    seed: int


class YoloTaskTrainingDataset:
    """普通 YOLO task 训练样本 Dataset。"""

    def __init__(self, samples: Sequence[Any]) -> None:
        self._samples = tuple(samples)

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> Any:
        return self._samples[int(index)]


@dataclass(frozen=True)
class YoloTaskBatchCollator:
    """普通 YOLO task batch collate 逻辑。"""

    base_input_size: tuple[int, int]
    augmentation_options: Any | None
    available_samples: Sequence[Any]
    build_batch: Callable[..., Any]
    load_imports: Callable[[], Any]
    resolve_batch_input_size: Callable[..., tuple[int, int]] | None = None

    def __call__(self, samples: list[Any]) -> Any:
        """在 DataLoader worker 中构建 CPU batch。"""

        input_size = self.base_input_size
        if self.resolve_batch_input_size is not None:
            input_size = self.resolve_batch_input_size(
                base_input_size=self.base_input_size,
                augmentation_options=self.augmentation_options,
            )
        return self.build_batch(
            samples=samples,
            input_size=input_size,
            device="cpu",
            precision="fp32",
            imports=self.load_imports(),
            augmentation_options=self.augmentation_options,
            available_samples=self.available_samples,
        )


def build_yolo_task_training_dataloader(
    *,
    torch_module: Any,
    samples: Sequence[Any],
    batch_size: int,
    input_size: tuple[int, int],
    augmentation_options: Any | None,
    plan: YoloTaskDataLoaderPlan,
    shuffle: bool,
    build_batch: Callable[..., Any],
    load_imports: Callable[[], Any],
    resolve_batch_input_size: Callable[..., tuple[int, int]] | None = None,
) -> Any:
    """创建普通 YOLO 非 detection task PyTorch DataLoader。"""

    dataset = YoloTaskTrainingDataset(samples=samples)
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
        "collate_fn": YoloTaskBatchCollator(
            base_input_size=input_size,
            augmentation_options=augmentation_options,
            available_samples=tuple(samples),
            build_batch=build_batch,
            load_imports=load_imports,
            resolve_batch_input_size=resolve_batch_input_size,
        ),
        "pin_memory": bool(plan.pin_memory),
        "drop_last": False,
        "generator": generator,
    }
    if num_workers > 0:
        loader_kwargs["worker_init_fn"] = seed_yolo_task_dataloader_worker
        loader_kwargs["persistent_workers"] = bool(plan.persistent_workers)
        loader_kwargs["prefetch_factor"] = max(1, int(plan.prefetch_factor))
    return YoloInfiniteDataLoader(dataset, torch_module=torch_module, **loader_kwargs)


def build_yolo_task_evaluation_dataloader(
    *,
    torch_module: Any,
    samples: Sequence[Any],
    input_size: tuple[int, int],
    plan: YoloTaskDataLoaderPlan,
    build_batch: Callable[..., Any],
    load_imports: Callable[[], Any],
    max_samples: int = 8,
) -> Any:
    """创建普通 YOLO task 训练期 validator DataLoader。"""

    selected_samples = tuple(samples[: max(0, int(max_samples))])
    return build_yolo_task_training_dataloader(
        torch_module=torch_module,
        samples=selected_samples,
        batch_size=1,
        input_size=input_size,
        augmentation_options=None,
        plan=plan,
        shuffle=False,
        build_batch=build_batch,
        load_imports=load_imports,
        resolve_batch_input_size=None,
    )


def resolve_yolo_task_evaluation_dataloader_plan(
    *,
    device: str,
    extra_options: dict[str, object] | None = None,
) -> YoloTaskDataLoaderPlan:
    """解析普通 YOLO task 训练期 validator DataLoader 参数。"""

    options = dict(extra_options or {})
    if "num_workers" not in options:
        options["num_workers"] = 0
    if "pin_memory" not in options:
        options["pin_memory"] = str(device).startswith("cuda")
    if "prefetch_factor" not in options:
        options["prefetch_factor"] = 2
    return resolve_yolo_task_dataloader_plan(
        extra_options=options,
        device=device,
    )


def replace_yolo_task_dataloader_plan_seed(
    *,
    plan: YoloTaskDataLoaderPlan,
    seed: int,
) -> YoloTaskDataLoaderPlan:
    """按 epoch 生成新的 DataLoader seed。"""

    return YoloTaskDataLoaderPlan(
        num_workers=plan.num_workers,
        pin_memory=plan.pin_memory,
        prefetch_factor=plan.prefetch_factor,
        persistent_workers=plan.persistent_workers,
        seed=int(plan.seed) + int(seed),
    )


def resolve_yolo_task_dataloader_plan(
    *,
    extra_options: dict[str, object],
    device: str,
) -> YoloTaskDataLoaderPlan:
    """解析普通 YOLO 非 detection task DataLoader 参数。"""

    num_workers = max(0, _read_int_option(extra_options, "num_workers", default=0))
    return YoloTaskDataLoaderPlan(
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


def move_yolo_task_batch_to_device(
    *,
    batch: Any,
    device: str,
    precision: str,
    torch_module: Any,
) -> Any:
    """把 DataLoader 产出的 CPU task batch 移到训练设备。"""

    return _move_value_to_device(
        value=batch,
        device=device,
        precision=precision,
        torch_module=torch_module,
    )


def pin_yolo_task_value(value: Any) -> Any:
    """递归 pin task batch 中的 Tensor。"""

    try:
        import torch  # noqa: PLC0415
    except ImportError:
        return value
    if torch.is_tensor(value):
        return value.pin_memory()
    if is_dataclass(value) and not isinstance(value, type):
        return replace(
            value,
            **{
                field.name: pin_yolo_task_value(getattr(value, field.name))
                for field in fields(value)
            },
        )
    if isinstance(value, dict):
        return {key: pin_yolo_task_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(pin_yolo_task_value(item) for item in value)
    if isinstance(value, list):
        return [pin_yolo_task_value(item) for item in value]
    return value


def _move_value_to_device(
    *,
    value: Any,
    device: str,
    precision: str,
    torch_module: Any,
) -> Any:
    """递归把 batch 对象中的 Tensor 移到训练设备。"""

    if torch_module.is_tensor(value):
        if value.is_floating_point():
            return move_yolo_tensor_to_training_device(
                value,
                device=device,
                runtime_precision=precision,
            )
        return value.to(device=device)
    if is_dataclass(value) and not isinstance(value, type):
        return replace(
            value,
            **{
                field.name: _move_value_to_device(
                    value=getattr(value, field.name),
                    device=device,
                    precision=precision,
                    torch_module=torch_module,
                )
                for field in fields(value)
            },
        )
    if isinstance(value, dict):
        return {
            key: _move_value_to_device(
                value=item,
                device=device,
                precision=precision,
                torch_module=torch_module,
            )
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(
            _move_value_to_device(
                value=item,
                device=device,
                precision=precision,
                torch_module=torch_module,
            )
            for item in value
        )
    if isinstance(value, list):
        return [
            _move_value_to_device(
                value=item,
                device=device,
                precision=precision,
                torch_module=torch_module,
            )
            for item in value
        ]
    return value


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


def load_yolo_task_dataloader_imports() -> Any:
    """延迟加载 task DataLoader worker 依赖。"""

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415

    return SimpleNamespace(cv2=cv2, np=np, torch=torch)


def seed_yolo_task_dataloader_worker(worker_id: int) -> None:
    """初始化 task DataLoader worker 的随机种子。"""

    del worker_id
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415

    worker_seed = int(torch.initial_seed() % 2**32)
    random.seed(worker_seed)
    np.random.seed(worker_seed)


__all__ = [
    "YoloTaskDataLoaderPlan",
    "build_yolo_task_evaluation_dataloader",
    "build_yolo_task_training_dataloader",
    "load_yolo_task_dataloader_imports",
    "move_yolo_task_batch_to_device",
    "pin_yolo_task_value",
    "replace_yolo_task_dataloader_plan_seed",
    "resolve_yolo_task_evaluation_dataloader_plan",
    "resolve_yolo_task_dataloader_plan",
]
