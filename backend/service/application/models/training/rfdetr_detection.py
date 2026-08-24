"""RF-DETR detection 训练执行模块。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.service.application.models.rfdetr_core.training.platform_runner import (
    RfdetrPlatformTrainingRequest,
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
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


RFDETR_IMPL_MODE = "rfdetr-full-core-detection"

_RF_DEFAULT_BATCH_SIZE = 2
_RF_DEFAULT_MAX_EPOCHS = 100


@dataclass(frozen=True)
class RfdetrTrainingBatchProgress:
    """描述 RF-DETR detection batch 级训练进度。"""

    epoch: int
    max_epochs: int
    iteration: int
    max_iterations: int
    global_iteration: int
    total_iterations: int
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class RfdetrTrainingEpochProgress:
    """描述 RF-DETR detection epoch 级训练进度。"""

    epoch: int
    max_epochs: int
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class RfdetrTrainingSavePoint:
    """描述 RF-DETR detection 保存点。"""

    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes | None
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float


@dataclass(frozen=True)
class RfdetrTrainingControlCommand:
    """描述训练控制命令。"""

    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


class RfdetrTrainingPausedError(Exception):
    """训练被暂停时抛出。"""

    def __init__(self, savepoint: RfdetrTrainingSavePoint) -> None:
        """保留暂停前已持久化所需的完整保存点。"""

        super().__init__("RF-DETR detection training paused")
        self.savepoint = savepoint


class RfdetrTrainingTerminatedError(Exception):
    """训练被终止时抛出。"""

    def __init__(self, savepoint: RfdetrTrainingSavePoint) -> None:
        """保留终止前已生成的完整保存点。"""

        super().__init__("RF-DETR detection training terminated")
        self.savepoint = savepoint


@dataclass(frozen=True)
class RfdetrTrainingExecutionRequest:
    """描述一次 RF-DETR detection 训练执行请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_scale: str = "nano"
    batch_size: int = _RF_DEFAULT_BATCH_SIZE
    max_epochs: int = _RF_DEFAULT_MAX_EPOCHS
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    resume_checkpoint_path: Path | None = None
    warm_start_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    extra_options: dict[str, object] | None = None
    batch_callback: Callable[[RfdetrTrainingBatchProgress], None] | None = None
    control_callback: Callable[[], RfdetrTrainingControlCommand | None] | None = None
    epoch_callback: Callable[
        [RfdetrTrainingEpochProgress],
        RfdetrTrainingControlCommand | None,
    ] | None = None
    savepoint_callback: Callable[[RfdetrTrainingSavePoint], None] | None = None


@dataclass(frozen=True)
class RfdetrTrainingExecutionResult:
    """描述一次 RF-DETR detection 训练执行结果。"""

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
def run_rfdetr_training(
    request: RfdetrTrainingExecutionRequest,
) -> RfdetrTrainingExecutionResult:
    """执行一轮 RF-DETR detection full-core 训练。"""

    try:
        result = run_rfdetr_platform_training(
            RfdetrPlatformTrainingRequest(
                dataset_storage=request.dataset_storage,
                manifest_payload=request.manifest_payload,
                task_type=DETECTION_TASK_TYPE,
                model_scale=request.model_scale,
                batch_size=request.batch_size,
                max_epochs=request.max_epochs,
                input_size=request.input_size
                or resolve_rfdetr_full_core_default_input_size(
                    task_type=DETECTION_TASK_TYPE,
                    model_scale=request.model_scale,
                ),
                precision=request.precision,
                resume_checkpoint_path=request.resume_checkpoint_path,
                warm_start_checkpoint_path=request.warm_start_checkpoint_path,
                warm_start_source_summary=request.warm_start_source_summary,
                extra_options=request.extra_options,
                batch_callback=_build_platform_batch_callback(request),
                control_callback=_build_platform_control_callback(request),
                epoch_callback=_build_platform_epoch_callback(request),
                savepoint_callback=_build_platform_savepoint_callback(request),
            )
        )
    except RfdetrPlatformTrainingControlSignal as signal:
        savepoint = _to_detection_savepoint(signal.savepoint)
        if signal.status == "terminated":
            raise RfdetrTrainingTerminatedError(savepoint) from signal
        raise RfdetrTrainingPausedError(savepoint) from signal
    return RfdetrTrainingExecutionResult(
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
    request: RfdetrTrainingExecutionRequest,
) -> Callable[[RfdetrPlatformBatchProgress], None] | None:
    """把 core batch progress 转换为 detection 公开进度。"""

    if request.batch_callback is None:
        return None

    def on_batch(progress: RfdetrPlatformBatchProgress) -> None:
        request.batch_callback(
            RfdetrTrainingBatchProgress(
                epoch=progress.epoch,
                max_epochs=progress.max_epochs,
                iteration=progress.iteration,
                max_iterations=progress.max_iterations,
                global_iteration=progress.global_iteration,
                total_iterations=progress.total_iterations,
                learning_rate=progress.learning_rate,
                train_metrics=dict(progress.train_metrics),
            )
        )

    return on_batch


def _build_platform_control_callback(
    request: RfdetrTrainingExecutionRequest,
) -> Callable[[], RfdetrPlatformTrainingControlCommand | None] | None:
    """把 detection batch 安全点控制命令转换到 core。"""

    if request.control_callback is None:
        return None

    def poll_control() -> RfdetrPlatformTrainingControlCommand | None:
        command = request.control_callback()
        if command is None:
            return None
        return RfdetrPlatformTrainingControlCommand(
            save_checkpoint=command.save_checkpoint,
            pause_training=command.pause_training,
            terminate_training=command.terminate_training,
        )

    return poll_control


def _build_platform_epoch_callback(
    request: RfdetrTrainingExecutionRequest,
) -> Callable[
    [RfdetrPlatformEpochProgress],
    RfdetrPlatformTrainingControlCommand | None,
] | None:
    """把公开 epoch 控制命令转换为 core 控制命令。"""

    if request.epoch_callback is None:
        return None

    def on_epoch(
        progress: RfdetrPlatformEpochProgress,
    ) -> RfdetrPlatformTrainingControlCommand | None:
        command = request.epoch_callback(
            RfdetrTrainingEpochProgress(
                epoch=progress.epoch,
                max_epochs=progress.max_epochs,
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
    request: RfdetrTrainingExecutionRequest,
) -> Callable[[RfdetrPlatformTrainingSavePoint], None] | None:
    """把 core 保存点转换为 detection 公开保存点。"""

    if request.savepoint_callback is None:
        return None

    def on_savepoint(savepoint: RfdetrPlatformTrainingSavePoint) -> None:
        request.savepoint_callback(_to_detection_savepoint(savepoint))

    return on_savepoint


def _to_detection_savepoint(
    savepoint: RfdetrPlatformTrainingSavePoint,
) -> RfdetrTrainingSavePoint:
    """复制 core 保存点，确保公开层不泄漏 Lightning 类型。"""

    return RfdetrTrainingSavePoint(
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
    "RFDETR_IMPL_MODE",
    "RfdetrTrainingBatchProgress",
    "RfdetrTrainingControlCommand",
    "RfdetrTrainingEpochProgress",
    "RfdetrTrainingExecutionRequest",
    "RfdetrTrainingExecutionResult",
    "RfdetrTrainingPausedError",
    "RfdetrTrainingSavePoint",
    "RfdetrTrainingTerminatedError",
    "run_rfdetr_training",
]
