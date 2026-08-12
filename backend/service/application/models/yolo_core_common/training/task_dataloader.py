"""普通 YOLO 非 detection 任务 DataLoader。"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass, replace
from types import SimpleNamespace
from typing import Any

import numpy as np

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.data.tensor_transfer import (
    move_yolo_tensor_to_training_device,
)
from backend.service.application.models.yolo_core_common.training.infinite_dataloader import (
    YoloInfiniteDataLoader,
    resolve_yolo_dataloader_batch_size,
    resolve_yolo_dataloader_worker_count,
)
from backend.service.application.models.yolo_core_common.training.worker_ipc import (
    serialize_yolo_worker_value,
)


@dataclass(frozen=True)
class YoloTaskDataLoaderPlan:
    """描述普通 YOLO task DataLoader 配置。"""

    num_workers: int
    pin_memory: bool
    prefetch_factor: int
    persistent_workers: bool
    seed: int


_UNRESOLVED_AUGMENTATION_OPTIONS = object()


class YoloTaskTrainingDataLoaderLifecycle:
    """跨 epoch 复用训练 DataLoader，只在增强阶段变化时重建。

    Windows ``spawn`` worker 的启动成本和常驻内存都很高。训练循环如果每个
    epoch 重建 loader，会让 ``persistent_workers`` 完全失效。本生命周期对象
    以实际增强配置为阶段键；正常训练复用同一批 worker，进入 close-mosaic
    阶段时重建一次，并在退出时显式回收。
    """

    def __init__(self, *, max_reuse_epochs: int | None = None) -> None:
        self._loader: Any | None = None
        self._augmentation_options: object = _UNRESOLVED_AUGMENTATION_OPTIONS
        self._resolved_epochs = 0
        # 默认不按 epoch 周期重建 worker。Windows ``spawn`` 一次需要重新导入
        # torch、OpenCV 和模型数据代码，固定每 4 轮回收会在 200 轮训练中制造
        # 数十分钟纯停顿。NumPy IPC 已避免逐 batch 累积 torch shared-memory
        # 映射，close 路径也会显式释放 Process 句柄；因此只在增强阶段变化、
        # 训练结束或调用方明确设置复用上限时回收。
        self._max_reuse_epochs = max(
            0,
            int(0 if max_reuse_epochs is None else max_reuse_epochs),
        )

    def resolve(
        self,
        *,
        augmentation_options: object | None,
        build_loader: Callable[[], Any],
    ) -> Any:
        """返回当前阶段 loader；配置变化时关闭旧 loader 后重新创建。"""

        recycle_workers = bool(
            self._loader is not None
            and int(getattr(self._loader, "num_workers", 0)) > 0
            and self._max_reuse_epochs > 0
            and self._resolved_epochs >= self._max_reuse_epochs
        )
        if (
            self._loader is None
            or self._augmentation_options != augmentation_options
            or recycle_workers
        ):
            self.close()
            self._loader = build_loader()
            self._augmentation_options = augmentation_options
        self._resolved_epochs += 1
        return self._loader

    def close(self) -> None:
        """显式释放当前 loader 及其 persistent workers。"""

        loader = self._loader
        self._loader = None
        self._augmentation_options = _UNRESOLVED_AUGMENTATION_OPTIONS
        self._resolved_epochs = 0
        if loader is None:
            return
        close = getattr(loader, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> YoloTaskTrainingDataLoaderLifecycle:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __del__(self) -> None:
        """异常退出训练循环时也回收 worker。"""

        try:
            self.close()
        except Exception:
            pass


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
    training: bool
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
        imports = self.load_imports()
        batch = self.build_batch(
            samples=samples,
            input_size=input_size,
            device="cpu",
            precision="fp32",
            imports=imports,
            training=self.training,
            augmentation_options=self.augmentation_options,
            available_samples=self.available_samples,
        )
        if imports.torch.utils.data.get_worker_info() is None:
            return batch
        return serialize_yolo_worker_value(
            value=batch,
            torch_module=imports.torch,
        )


def build_yolo_task_training_dataloader(
    *,
    torch_module: Any,
    samples: Sequence[Any],
    batch_size: int,
    input_size: tuple[int, int],
    training: bool,
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
            training=bool(training),
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
    batch_size: int = 1,
    input_size: tuple[int, int],
    plan: YoloTaskDataLoaderPlan,
    build_batch: Callable[..., Any],
    load_imports: Callable[[], Any],
    max_samples: int | None = None,
) -> Any:
    """创建普通 YOLO task 训练期 validator DataLoader。

    默认消费完整 validation split。只有显式传入 ``max_samples`` 时才用于
    调试性快速评估，避免最佳 checkpoint 被验证集前几张图片误导。
    """

    selected_samples = (
        tuple(samples)
        if max_samples is None
        else tuple(samples[: max(0, int(max_samples))])
    )
    return build_yolo_task_training_dataloader(
        torch_module=torch_module,
        samples=selected_samples,
        batch_size=batch_size,
        input_size=input_size,
        training=False,
        augmentation_options=None,
        plan=plan,
        shuffle=False,
        build_batch=build_batch,
        load_imports=load_imports,
        resolve_batch_input_size=None,
    )


@contextmanager
def managed_yolo_task_evaluation_dataloader(loader: Any) -> Iterator[Any]:
    """托管 validator DataLoader，并在正常或异常退出时回收 worker。"""

    try:
        yield loader
    finally:
        close_yolo_dataloader(loader)


def close_yolo_dataloader(loader: Any) -> None:
    """显式关闭支持 ``close`` 的 YOLO DataLoader。"""

    close = getattr(loader, "close", None)
    if callable(close):
        close()


def iter_yolo_task_evaluation_items(
    *,
    targets: Sequence[Any],
    batched_outputs: Sequence[Any],
    image_index_start: int,
) -> Iterator[tuple[int, Any, tuple[Any, ...]]]:
    """校验 batch 维并逐图切分 validator 输出。

    evaluator 在 GPU 上执行一次批量前向，但现有后处理器以单图输入为契约。
    此函数保留 batch 维切片，确保预测、target 与连续 ``image_id`` 一一对应。
    """

    target_items = tuple(targets)
    batch_size = len(target_items)
    for output_index, output in enumerate(batched_outputs):
        shape = getattr(output, "shape", None)
        if shape is None or len(shape) < 1:
            raise InvalidRequestError(
                "YOLO task validator 输出缺少 batch 维",
                details={"output_index": output_index},
            )
        output_batch_size = int(shape[0])
        if output_batch_size != batch_size:
            raise InvalidRequestError(
                "YOLO task validator 输出与 target batch 数量不一致",
                details={
                    "output_index": output_index,
                    "output_batch_size": output_batch_size,
                    "target_batch_size": batch_size,
                },
            )
    for batch_offset, target in enumerate(target_items):
        yield (
            int(image_index_start) + batch_offset,
            target,
            tuple(
                output[batch_offset : batch_offset + 1] for output in batched_outputs
            ),
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

    num_workers = max(0, _read_int_option(extra_options, "num_workers", default=2))
    return YoloTaskDataLoaderPlan(
        num_workers=num_workers,
        pin_memory=_read_bool_option(
            extra_options,
            "pin_memory",
            default=str(device).startswith("cuda"),
        ),
        prefetch_factor=max(
            1,
            _read_int_option(extra_options, "prefetch_factor", default=2),
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
    if isinstance(value, np.ndarray):
        # worker 以 NumPy 传输 batch，避免 Windows torch multiprocessing
        # 为每批 Tensor 累积共享内存映射；在主进程 pin 阶段恢复 Tensor。
        return torch.from_numpy(value).pin_memory()
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

    if isinstance(value, np.ndarray):
        value = torch_module.from_numpy(value)
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
    "YoloTaskTrainingDataLoaderLifecycle",
    "build_yolo_task_evaluation_dataloader",
    "build_yolo_task_training_dataloader",
    "load_yolo_task_dataloader_imports",
    "move_yolo_task_batch_to_device",
    "pin_yolo_task_value",
    "replace_yolo_task_dataloader_plan_seed",
    "resolve_yolo_task_evaluation_dataloader_plan",
    "resolve_yolo_task_dataloader_plan",
]
