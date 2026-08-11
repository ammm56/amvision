"""RF-DETR segmentation 训练执行模块。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.service.application.models.rfdetr_core.training.platform_runner import (
    RfdetrPlatformTrainingRequest,
    resolve_rfdetr_platform_training_input_size,
    run_rfdetr_platform_training,
)
from backend.service.application.models.rfdetr_core.training.platform_control import (
    RfdetrPlatformBatchProgress,
    RfdetrPlatformEpochProgress,
    RfdetrPlatformTrainingControlCommand,
    RfdetrPlatformTrainingControlSignal,
    RfdetrPlatformTrainingSavePoint,
)
from backend.service.application.models.rfdetr_core.factory import (
    resolve_rfdetr_full_core_default_input_size,
)
from backend.service.application.models.training.training_engine import (
    training_engine_entrypoint,
)
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


RFDETR_SEGMENTATION_IMPLEMENTATION_MODE = "rfdetr-full-core-segmentation"

_RF_SEG_DEFAULT_BATCH_SIZE = 1
_RF_SEG_DEFAULT_EPOCHS = 100


@dataclass(frozen=True)
class RfdetrSegmentationTrainingBatchProgress:
    """描述 RF-DETR segmentation 每个真实 batch 的进度。"""

    epoch: int
    max_epochs: int
    iteration: int
    max_iterations: int
    global_iteration: int
    total_iterations: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class RfdetrSegmentationTrainingEpochProgress:
    """描述 RF-DETR segmentation 每个 epoch 的进度。"""

    epoch: int
    max_epochs: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class RfdetrSegmentationTrainingSavePoint:
    """描述 RF-DETR segmentation 保存点。"""

    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes | None
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

    def __init__(self, savepoint: RfdetrSegmentationTrainingSavePoint) -> None:
        """保留暂停前生成的完整保存点。"""

        super().__init__("RF-DETR segmentation training paused")
        self.savepoint = savepoint


class RfdetrSegmentationTrainingTerminatedError(Exception):
    """训练被显式终止。"""

    def __init__(self, savepoint: RfdetrSegmentationTrainingSavePoint) -> None:
        """保留终止前生成的完整保存点。"""

        super().__init__("RF-DETR segmentation training terminated")
        self.savepoint = savepoint


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
    warm_start_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    extra_options: dict[str, object] | None = None
    batch_callback: Callable[
        [RfdetrSegmentationTrainingBatchProgress],
        None,
    ] | None = None
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
    warm_start_summary: dict[str, object]
    best_checkpoint_bytes: bytes | None = None
    test_metrics_payload: dict[str, object] | None = None


@training_engine_entrypoint
def run_rfdetr_segmentation_training(
    request: RfdetrSegmentationTrainingExecutionRequest,
) -> RfdetrSegmentationTrainingExecutionResult:
    """执行一次 RF-DETR segmentation full-core 训练。"""

    requested_input_size = request.input_size or resolve_rfdetr_full_core_default_input_size(
        task_type=SEGMENTATION_TASK_TYPE,
        model_scale=request.model_scale,
    )
    aligned_input_size = resolve_rfdetr_platform_training_input_size(
        task_type=SEGMENTATION_TASK_TYPE,
        model_scale=request.model_scale,
        input_size=requested_input_size,
    )
    try:
        result = run_rfdetr_platform_training(
            RfdetrPlatformTrainingRequest(
                dataset_storage=request.dataset_storage,
                manifest_payload=request.manifest_payload,
                task_type=SEGMENTATION_TASK_TYPE,
                model_scale=request.model_scale,
                batch_size=request.batch_size,
                max_epochs=request.max_epochs,
                input_size=aligned_input_size,
                precision=request.precision,
                resume_checkpoint_path=request.resume_checkpoint_path,
                warm_start_checkpoint_path=request.warm_start_checkpoint_path,
                warm_start_source_summary=request.warm_start_source_summary,
                extra_options=request.extra_options,
                batch_callback=_build_platform_batch_callback(
                    request,
                    input_size=aligned_input_size,
                ),
                epoch_callback=_build_platform_epoch_callback(
                    request,
                    input_size=aligned_input_size,
                ),
                savepoint_callback=_build_platform_savepoint_callback(request),
            )
        )
    except RfdetrPlatformTrainingControlSignal as signal:
        savepoint = _to_segmentation_savepoint(signal.savepoint)
        if signal.status == "terminated":
            raise RfdetrSegmentationTrainingTerminatedError(savepoint) from signal
        raise RfdetrSegmentationTrainingPausedError(savepoint) from signal
    return RfdetrSegmentationTrainingExecutionResult(
        best_metric_value=result.best_metric_value,
        best_metric_name=result.best_metric_name,
        latest_checkpoint_bytes=result.latest_checkpoint_bytes,
        metrics_payload=result.metrics_payload,
        validation_metrics_payload=result.validation_metrics_payload,
        labels=result.labels,
        aligned_input_size=result.aligned_input_size,
        warm_start_summary=result.warm_start_summary,
        best_checkpoint_bytes=result.best_checkpoint_bytes,
        test_metrics_payload=result.test_metrics_payload,
    )


def _build_platform_batch_callback(
    request: RfdetrSegmentationTrainingExecutionRequest,
    *,
    input_size: tuple[int, int],
) -> Callable[[RfdetrPlatformBatchProgress], None] | None:
    """把 core batch progress 转换为 segmentation 公开进度。"""

    if request.batch_callback is None:
        return None

    def on_batch(progress: RfdetrPlatformBatchProgress) -> None:
        request.batch_callback(
            RfdetrSegmentationTrainingBatchProgress(
                epoch=progress.epoch,
                max_epochs=progress.max_epochs,
                iteration=progress.iteration,
                max_iterations=progress.max_iterations,
                global_iteration=progress.global_iteration,
                total_iterations=progress.total_iterations,
                input_size=input_size,
                learning_rate=progress.learning_rate,
                train_metrics=dict(progress.train_metrics),
            )
        )

    return on_batch


def _build_platform_epoch_callback(
    request: RfdetrSegmentationTrainingExecutionRequest,
    *,
    input_size: tuple[int, int],
) -> Callable[
    [RfdetrPlatformEpochProgress],
    RfdetrPlatformTrainingControlCommand | None,
] | None:
    """把 segmentation epoch 控制命令转换为 core 控制命令。"""

    if request.epoch_callback is None:
        return None

    def on_epoch(
        progress: RfdetrPlatformEpochProgress,
    ) -> RfdetrPlatformTrainingControlCommand | None:
        command = request.epoch_callback(
            RfdetrSegmentationTrainingEpochProgress(
                epoch=progress.epoch,
                max_epochs=progress.max_epochs,
                input_size=input_size,
                learning_rate=progress.learning_rate,
                train_metrics=dict(progress.train_metrics),
            )
        )
        if command is None:
            return None
        return RfdetrPlatformTrainingControlCommand(
            save_checkpoint=command.save_checkpoint,
            pause_training=command.pause_training,
            terminate_training=command.terminate_training,
        )

    return on_epoch


def _build_platform_savepoint_callback(
    request: RfdetrSegmentationTrainingExecutionRequest,
) -> Callable[[RfdetrPlatformTrainingSavePoint], None] | None:
    """把 core 保存点转换为 segmentation 公开保存点。"""

    if request.savepoint_callback is None:
        return None

    def on_savepoint(savepoint: RfdetrPlatformTrainingSavePoint) -> None:
        request.savepoint_callback(_to_segmentation_savepoint(savepoint))

    return on_savepoint


def _to_segmentation_savepoint(
    savepoint: RfdetrPlatformTrainingSavePoint,
) -> RfdetrSegmentationTrainingSavePoint:
    """复制 core 保存点，确保公开层不泄漏 Lightning 类型。"""

    return RfdetrSegmentationTrainingSavePoint(
        latest_checkpoint_bytes=savepoint.latest_checkpoint_bytes,
        best_checkpoint_bytes=savepoint.best_checkpoint_bytes,
        train_metrics=dict(savepoint.train_metrics),
        validation_metrics=dict(savepoint.validation_metrics),
        best_metric_value=savepoint.best_metric_value,
        best_metric_name=savepoint.best_metric_name,
        epoch=savepoint.epoch,
        learning_rate=savepoint.learning_rate,
    )


__all__ = [
    "RFDETR_SEGMENTATION_IMPLEMENTATION_MODE",
    "RfdetrSegmentationTrainingBatchProgress",
    "RfdetrSegmentationTrainingControlCommand",
    "RfdetrSegmentationTrainingEpochProgress",
    "RfdetrSegmentationTrainingExecutionRequest",
    "RfdetrSegmentationTrainingExecutionResult",
    "RfdetrSegmentationTrainingPausedError",
    "RfdetrSegmentationTrainingSavePoint",
    "RfdetrSegmentationTrainingTerminatedError",
    "run_rfdetr_segmentation_training",
]
