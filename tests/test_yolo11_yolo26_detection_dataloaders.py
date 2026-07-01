"""YOLO11 / YOLO26 detection DataLoader 边界测试。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import torch

from backend.service.application.models.yolo11_core.data.detection import (
    Yolo11DetectionTrainingAnnotation,
    Yolo11DetectionTrainingSample,
    build_yolo11_detection_training_batch_cpu,
)
from backend.service.application.models.yolo11_core.training.pytorch_dataloader import (
    Yolo11DetectionDataLoaderPlan,
    build_yolo11_detection_training_dataloader,
    load_yolo11_detection_dataloader_imports,
)
from backend.service.application.models.yolo26_core.data.detection import (
    Yolo26DetectionTrainingAnnotation,
    Yolo26DetectionTrainingSample,
    build_yolo26_detection_training_batch_cpu,
)
from backend.service.application.models.yolo26_core.training.pytorch_dataloader import (
    Yolo26DetectionDataLoaderPlan,
    build_yolo26_detection_training_dataloader,
    load_yolo26_detection_dataloader_imports,
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

    batch = next(iter(dataloader))

    assert tuple(batch.images.shape) == (2, 3, 64, 64)
    assert batch.images.device.type == "cpu"
    assert len(batch.targets) == 2
    assert batch.targets[0].letterbox_transform is not None
    assert batch.targets[0].boxes_xyxy


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

    batch = next(iter(dataloader))

    assert tuple(batch.images.shape) == (2, 3, 64, 64)
    assert batch.images.device.type == "cpu"
    assert len(batch.targets) == 2
    assert batch.targets[1].letterbox_transform is not None
    assert batch.targets[1].boxes_xyxy


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
