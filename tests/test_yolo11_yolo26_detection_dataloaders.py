"""YOLO11 / YOLO26 detection DataLoader 边界测试。"""

from __future__ import annotations

from pathlib import Path
from contextlib import nullcontext

import pytest

import cv2
import numpy as np
import torch

from backend.service.application.models.yolo11_core.data.detection import (
    Yolo11DetectionTrainingAnnotation,
    Yolo11DetectionTrainingSample,
    build_yolo11_detection_training_batch_cpu,
)
from backend.service.application.models.yolo11_core.training.pytorch_dataloader import (
    Yolo11DetectionBatchCollator,
    Yolo11DetectionDataLoaderBatch,
    Yolo11DetectionDataLoaderPlan,
    build_yolo11_detection_training_dataloader,
    load_yolo11_detection_dataloader_imports,
)
from backend.service.application.models.yolo11_core.training.runner import (
    run_yolo11_detection_training_epoch,
)
from backend.service.application.models.yolo26_core.data.detection import (
    Yolo26DetectionTrainingAnnotation,
    Yolo26DetectionTrainingSample,
    build_yolo26_detection_training_batch_cpu,
)
from backend.service.application.models.yolo26_core.training.pytorch_dataloader import (
    Yolo26DetectionBatchCollator,
    Yolo26DetectionDataLoaderBatch,
    Yolo26DetectionDataLoaderPlan,
    build_yolo26_detection_training_dataloader,
    load_yolo26_detection_dataloader_imports,
)
from backend.service.application.models.yolo26_core.training.runner import (
    run_yolo26_detection_training_epoch,
)


def test_yolo11_detection_dataloader_returns_cpu_batch(tmp_path: Path) -> None:
    """YOLO11 DataLoader 应产出 CPU tensor 与 letterbox target。"""

    samples = _build_yolo11_samples(tmp_path)
    dataloader = build_yolo11_detection_training_dataloader(
        torch_module=torch,
        samples=samples,
        batch_size=2,
        input_size=(64, 64),
        augment_training=False,
        augmentation_options=None,
        plan=Yolo11DetectionDataLoaderPlan(
            num_workers=0,
            pin_memory=False,
            prefetch_factor=4,
            persistent_workers=False,
            seed=7,
        ),
        shuffle=False,
    )

    assert len(dataloader) == 1
    assert callable(getattr(dataloader, "reset", None))
    batch = next(iter(dataloader))

    assert tuple(batch.images.shape) == (2, 3, 64, 64)
    assert batch.images.device.type == "cpu"
    assert len(batch.targets) == 2
    assert batch.targets[0].letterbox_transform is not None
    assert batch.targets[0].boxes_xyxy
    dataloader.reset()


def test_yolo26_detection_dataloader_returns_cpu_batch(tmp_path: Path) -> None:
    """YOLO26 DataLoader 应产出 CPU tensor 与 letterbox target。"""

    samples = _build_yolo26_samples(tmp_path)
    dataloader = build_yolo26_detection_training_dataloader(
        torch_module=torch,
        samples=samples,
        batch_size=2,
        input_size=(64, 64),
        augment_training=False,
        augmentation_options=None,
        plan=Yolo26DetectionDataLoaderPlan(
            num_workers=0,
            pin_memory=False,
            prefetch_factor=4,
            persistent_workers=False,
            seed=11,
        ),
        shuffle=False,
    )

    assert len(dataloader) == 1
    assert callable(getattr(dataloader, "reset", None))
    batch = next(iter(dataloader))

    assert tuple(batch.images.shape) == (2, 3, 64, 64)
    assert batch.images.device.type == "cpu"
    assert len(batch.targets) == 2
    assert batch.targets[1].letterbox_transform is not None
    assert batch.targets[1].boxes_xyxy
    dataloader.reset()


def test_yolo11_yolo26_cpu_batch_builders_keep_images_on_cpu(
    tmp_path: Path,
) -> None:
    """CPU batch builder 不应提前把图像搬到 CUDA。"""

    yolo11_images, _ = build_yolo11_detection_training_batch_cpu(
        imports=load_yolo11_detection_dataloader_imports(),
        samples=_build_yolo11_samples(tmp_path),
        input_size=(64, 64),
    )
    yolo26_images, _ = build_yolo26_detection_training_batch_cpu(
        imports=load_yolo26_detection_dataloader_imports(),
        samples=_build_yolo26_samples(tmp_path),
        input_size=(64, 64),
    )

    assert yolo11_images.device.type == "cpu"
    assert yolo26_images.device.type == "cpu"


@pytest.mark.parametrize(
    ("collator_type", "batch_builder_path"),
    (
        (
            Yolo11DetectionBatchCollator,
            "backend.service.application.models.yolo11_core.training."
            "pytorch_dataloader.build_yolo11_detection_training_batch_cpu",
        ),
        (
            Yolo26DetectionBatchCollator,
            "backend.service.application.models.yolo26_core.training."
            "pytorch_dataloader.build_yolo26_detection_training_batch_cpu",
        ),
    ),
)
def test_yolo11_yolo26_worker_collators_use_numpy_ipc(
    monkeypatch: pytest.MonkeyPatch,
    collator_type: type,
    batch_builder_path: str,
) -> None:
    """worker batch 使用独立 NumPy IPC，避免系统 commit 随 batch 线性增长。"""

    monkeypatch.setattr(torch.utils.data, "get_worker_info", lambda: object())
    monkeypatch.setattr(
        batch_builder_path,
        lambda **_kwargs: (torch.ones((1, 3, 2, 2)), (object(),)),
    )
    collator = collator_type(
        input_size=(2, 2),
        augment_training=True,
        available_samples=(),
        augmentation_options=None,
    )

    batch = collator([object()])

    assert isinstance(batch.images, np.ndarray)
    assert batch.images.base is None


@pytest.mark.parametrize(
    ("batch_type", "run_epoch"),
    (
        (Yolo11DetectionDataLoaderBatch, run_yolo11_detection_training_epoch),
        (Yolo26DetectionDataLoaderBatch, run_yolo26_detection_training_epoch),
    ),
)
def test_yolo11_yolo26_epoch_runners_restore_numpy_worker_batches(
    batch_type: type,
    run_epoch: object,
) -> None:
    """主训练进程会把 worker 的 NumPy image 载荷恢复为 Tensor。"""

    model = torch.nn.Linear(1, 1)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    initial_weight = model.weight.detach().clone()
    batch = batch_type(
        images=np.asarray([[1.0]], dtype=np.float32),
        targets=(torch.tensor([[1.0]], dtype=torch.float32),),
        input_size=(1, 1),
    )

    result = run_epoch(
        torch_module=torch,
        model=model,
        samples=(1.0,),
        batch_size=1,
        input_size=(1, 1),
        epoch=1,
        max_epochs=1,
        global_iteration=0,
        total_iterations=1,
        optimizer=optimizer,
        scaler=_NoopGradScaler(),
        autocast_context=nullcontext,
        build_batch=_build_linear_training_batch,
        unwrap_outputs=lambda output: {"prediction": output},
        compute_loss=_compute_linear_training_loss,
        grad_clip_norm=10.0,
        dataloader_batches=(batch,),
        device="cpu",
        runtime_precision="fp32",
    )

    assert result.global_iteration == 1
    assert torch.equal(model.weight.detach(), initial_weight) is False


class _NoopGradScaler:
    """提供 CPU 单测需要的 GradScaler 最小接口。"""

    def scale(self, loss: torch.Tensor) -> torch.Tensor:
        return loss

    def unscale_(self, _optimizer: object) -> None:
        return None

    def step(self, optimizer: torch.optim.Optimizer) -> None:
        optimizer.step()

    def update(self) -> None:
        return None

    def get_scale(self) -> float:
        return 1.0


def _build_linear_training_batch(
    samples: list[float],
    _available_samples: tuple[float, ...],
    _epoch: int,
) -> tuple[torch.Tensor, tuple[torch.Tensor, ...]]:
    inputs = torch.tensor(samples, dtype=torch.float32).reshape(-1, 1)
    return inputs, tuple(inputs[index : index + 1] for index in range(len(samples)))


def _compute_linear_training_loss(
    *, raw_outputs: dict[str, torch.Tensor], batch_targets: tuple[torch.Tensor, ...], **_kwargs: object
) -> dict[str, torch.Tensor]:
    target = torch.cat(batch_targets, dim=0)
    loss = torch.nn.functional.mse_loss(raw_outputs["prediction"], target)
    return {
        "loss": loss,
        "class_loss": loss,
        "box_loss": loss * 0.0,
        "dfl_loss": loss * 0.0,
    }


def _build_yolo11_samples(
    tmp_path: Path,
) -> tuple[Yolo11DetectionTrainingSample, ...]:
    image_paths = _write_sample_images(tmp_path)
    return (
        Yolo11DetectionTrainingSample(
            image_id=1,
            image_path=image_paths[0],
            image_width=96,
            image_height=48,
            annotations=(
                Yolo11DetectionTrainingAnnotation(
                    category_index=0,
                    category_id=1,
                    bbox_xyxy=(10.0, 8.0, 70.0, 35.0),
                ),
            ),
        ),
        Yolo11DetectionTrainingSample(
            image_id=2,
            image_path=image_paths[1],
            image_width=96,
            image_height=48,
            annotations=(
                Yolo11DetectionTrainingAnnotation(
                    category_index=1,
                    category_id=2,
                    bbox_xyxy=(20.0, 12.0, 90.0, 42.0),
                ),
            ),
        ),
    )


def _build_yolo26_samples(
    tmp_path: Path,
) -> tuple[Yolo26DetectionTrainingSample, ...]:
    image_paths = _write_sample_images(tmp_path)
    return (
        Yolo26DetectionTrainingSample(
            image_id=1,
            image_path=image_paths[0],
            image_width=96,
            image_height=48,
            annotations=(
                Yolo26DetectionTrainingAnnotation(
                    category_index=0,
                    category_id=1,
                    bbox_xyxy=(10.0, 8.0, 70.0, 35.0),
                ),
            ),
        ),
        Yolo26DetectionTrainingSample(
            image_id=2,
            image_path=image_paths[1],
            image_width=96,
            image_height=48,
            annotations=(
                Yolo26DetectionTrainingAnnotation(
                    category_index=1,
                    category_id=2,
                    bbox_xyxy=(20.0, 12.0, 90.0, 42.0),
                ),
            ),
        ),
    )


def _write_sample_images(tmp_path: Path) -> tuple[Path, Path]:
    image_paths: list[Path] = []
    for index in range(2):
        image = np.full((48, 96, 3), 32 + index * 64, dtype=np.uint8)
        image_path = tmp_path / f"sample-{index}.jpg"
        assert cv2.imwrite(str(image_path), image)
        image_paths.append(image_path)
    return (image_paths[0], image_paths[1])
