"""RF-DETR segmentation 训练执行模块。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.service.application.models.rfdetr_core.training.platform_runner import (
    RfdetrPlatformTrainingRequest,
    RfdetrPlatformTrainingResult,
    run_rfdetr_platform_training,
)
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


RFDETR_SEGMENTATION_IMPLEMENTATION_MODE = "rfdetr-full-core-segmentation"

_RF_SEG_DEFAULT_INPUT = (384, 384)
_RF_SEG_DEFAULT_BATCH_SIZE = 1
_RF_SEG_DEFAULT_EPOCHS = 1


@dataclass(frozen=True)
class RfdetrSegmentationTrainingEpochProgress:
    """描述 RF-DETR segmentation 每个 epoch 的进度。"""

    epoch: int
    max_epochs: int
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class RfdetrSegmentationTrainingSavePoint:
    """描述 RF-DETR segmentation 保存点。"""

    latest_checkpoint_bytes: bytes
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float


@dataclass(frozen=True)
class RfdetrSegmentationTrainingControlCommand:
    """描述训练控制命令。"""

    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


class RfdetrSegmentationTrainingPausedError(Exception):
    """训练被显式暂停。"""


class RfdetrSegmentationTrainingTerminatedError(Exception):
    """训练被显式终止。"""


@dataclass(frozen=True)
class RfdetrSegmentationTrainingExecutionRequest:
    """描述一次 RF-DETR segmentation 训练执行请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_scale: str = "nano"
    batch_size: int = _RF_SEG_DEFAULT_BATCH_SIZE
    max_epochs: int = _RF_SEG_DEFAULT_EPOCHS
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    resume_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: Callable[
        [RfdetrSegmentationTrainingEpochProgress],
        RfdetrSegmentationTrainingControlCommand | None,
    ] | None = None
    savepoint_callback: Callable[
        [RfdetrSegmentationTrainingSavePoint],
        None,
    ] | None = None


@dataclass(frozen=True)
class RfdetrSegmentationTrainingExecutionResult:
    """描述一次 RF-DETR segmentation 训练执行结果。"""

    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]
    aligned_input_size: tuple[int, int]


def run_rfdetr_segmentation_training(
    request: RfdetrSegmentationTrainingExecutionRequest,
) -> RfdetrSegmentationTrainingExecutionResult:
    """执行一次 RF-DETR segmentation full-core 训练。"""

    result = run_rfdetr_platform_training(
        RfdetrPlatformTrainingRequest(
            dataset_storage=request.dataset_storage,
            manifest_payload=request.manifest_payload,
            task_type=SEGMENTATION_TASK_TYPE,
            model_scale=request.model_scale,
            batch_size=request.batch_size,
            max_epochs=request.max_epochs,
            input_size=request.input_size or _RF_SEG_DEFAULT_INPUT,
            precision=request.precision,
            resume_checkpoint_path=request.resume_checkpoint_path,
            extra_options=request.extra_options,
        )
    )
    _emit_final_callbacks(request, result)
    return RfdetrSegmentationTrainingExecutionResult(
        best_metric_value=result.best_metric_value,
        best_metric_name=result.best_metric_name,
        latest_checkpoint_bytes=result.latest_checkpoint_bytes,
        metrics_payload=result.metrics_payload,
        validation_metrics_payload=result.validation_metrics_payload,
        labels=result.labels,
        aligned_input_size=result.aligned_input_size,
    )


def _emit_final_callbacks(
    request: RfdetrSegmentationTrainingExecutionRequest,
    result: RfdetrPlatformTrainingResult,
) -> None:
    """向旧 service 控制面发送最终进度与保存点。"""

    train_metrics = {
        key: value
        for key, value in result.metrics_payload.get("callback_metrics", {}).items()
        if isinstance(value, int | float)
    }
    validation_metrics = {
        key: value
        for key, value in result.validation_metrics_payload.items()
        if isinstance(value, int | float)
    }
    if request.epoch_callback is not None:
        command = request.epoch_callback(
            RfdetrSegmentationTrainingEpochProgress(
                epoch=max(1, request.max_epochs),
                max_epochs=max(1, request.max_epochs),
                learning_rate=float((request.extra_options or {}).get("learning_rate", 1e-4)),
                train_metrics=train_metrics,
            )
        )
        if command is not None:
            if command.terminate_training:
                raise RfdetrSegmentationTrainingTerminatedError()
            if command.pause_training:
                raise RfdetrSegmentationTrainingPausedError()
    if request.savepoint_callback is not None:
        request.savepoint_callback(
            RfdetrSegmentationTrainingSavePoint(
                latest_checkpoint_bytes=result.latest_checkpoint_bytes,
                train_metrics=train_metrics,
                validation_metrics=validation_metrics,
                best_metric_value=result.best_metric_value,
                best_metric_name=result.best_metric_name,
                epoch=max(1, request.max_epochs),
                learning_rate=float((request.extra_options or {}).get("learning_rate", 1e-4)),
            )
        )


__all__ = [
    "RFDETR_SEGMENTATION_IMPLEMENTATION_MODE",
    "RfdetrSegmentationTrainingControlCommand",
    "RfdetrSegmentationTrainingEpochProgress",
    "RfdetrSegmentationTrainingExecutionRequest",
    "RfdetrSegmentationTrainingExecutionResult",
    "RfdetrSegmentationTrainingPausedError",
    "RfdetrSegmentationTrainingSavePoint",
    "RfdetrSegmentationTrainingTerminatedError",
    "run_rfdetr_segmentation_training",
]
