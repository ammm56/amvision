"""YOLO detection 训练执行 DTO。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.service.application.models.yolo_detection_training_control import (
    YoloDetectionTrainingBatchProgress,
    YoloDetectionTrainingControlCommand,
    YoloDetectionTrainingEpochProgress,
    YoloDetectionTrainingSavePoint,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class YoloDetectionTrainingExecutionRequest:
    """描述一次 YOLO detection 训练执行请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_scale: str
    model_type: str
    implementation_mode: str
    evaluation_interval: int | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    gpu_count: int | None = None
    precision: str | None = None
    warm_start_checkpoint_path: Path | None = None
    resume_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    input_size: tuple[int, int] | None = None
    extra_options: dict[str, object] | None = None
    batch_callback: Callable[[YoloDetectionTrainingBatchProgress], None] | None = None
    epoch_callback: (
        Callable[
            [YoloDetectionTrainingEpochProgress],
            YoloDetectionTrainingControlCommand | None,
        ]
        | None
    ) = None
    savepoint_callback: Callable[[YoloDetectionTrainingSavePoint], None] | None = None


@dataclass(frozen=True)
class YoloDetectionTrainingExecutionResult:
    """描述一次 YOLO detection 训练执行结果。"""

    checkpoint_bytes: bytes
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    warm_start_summary: dict[str, object]
    implementation_mode: str
    best_metric_name: str
    best_metric_value: float
    evaluation_interval: int
    category_names: tuple[str, ...]
    split_names: tuple[str, ...]
    sample_count: int
    train_sample_count: int
    input_size: tuple[int, int]
    batch_size: int
    max_epochs: int
    device: str
    gpu_count: int
    device_ids: tuple[int, ...]
    distributed_mode: str
    precision: str
    validation_split_name: str | None
    validation_sample_count: int
    parameter_count: int


__all__ = [
    "YoloDetectionTrainingExecutionRequest",
    "YoloDetectionTrainingExecutionResult",
]
