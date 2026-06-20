"""YOLO11 segmentation 训练任务执行适配器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.application.models.yolo11_segmentation_training import (
    Yolo11SegmentationTrainingControlCommand,
    Yolo11SegmentationTrainingEpochProgress,
    Yolo11SegmentationTrainingExecutionRequest,
    Yolo11SegmentationTrainingExecutionResult,
    Yolo11SegmentationTrainingSavePoint,
    run_yolo11_segmentation_training,
)


class Yolo11SegmentationTaskExecutionRequest(Protocol):
    """描述平台传入 YOLO11 segmentation 训练执行层的字段集合。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_type: str
    model_scale: str
    batch_size: int
    max_epochs: int
    evaluation_interval: int
    input_size: tuple[int, int] | None
    precision: str
    resume_checkpoint_path: Path | None
    extra_options: dict[str, object] | None
    epoch_callback: Any
    savepoint_callback: Any


class _TrainingControlCommandLike(Protocol):
    """描述训练控制命令需要读取的字段。"""

    save_checkpoint: bool
    pause_training: bool
    terminate_training: bool


def run_yolo11_segmentation_training_from_task_request(
    request: Yolo11SegmentationTaskExecutionRequest,
) -> Yolo11SegmentationTrainingExecutionResult:
    """把平台 segmentation task request 转成 YOLO11 专属训练请求。"""

    return run_yolo11_segmentation_training(
        Yolo11SegmentationTrainingExecutionRequest(
            dataset_storage=request.dataset_storage,
            manifest_payload=request.manifest_payload,
            model_type=request.model_type,
            model_scale=request.model_scale,
            batch_size=request.batch_size,
            max_epochs=request.max_epochs,
            evaluation_interval=request.evaluation_interval,
            input_size=request.input_size,
            precision=request.precision,
            resume_checkpoint_path=request.resume_checkpoint_path,
            extra_options=request.extra_options,
            epoch_callback=_build_yolo11_epoch_callback(request),
            savepoint_callback=_build_yolo11_savepoint_callback(request),
        )
    )


def _build_yolo11_epoch_callback(
    request: Yolo11SegmentationTaskExecutionRequest,
):
    """把平台 epoch callback 适配成 YOLO11 callback。"""

    if request.epoch_callback is None:
        return None

    def on_yolo11_epoch(
        progress: Yolo11SegmentationTrainingEpochProgress,
    ) -> Yolo11SegmentationTrainingControlCommand | None:
        command = request.epoch_callback(progress)
        if command is None:
            return None
        return _convert_yolo11_control_command(command)

    return on_yolo11_epoch


def _build_yolo11_savepoint_callback(
    request: Yolo11SegmentationTaskExecutionRequest,
):
    """把平台 savepoint callback 适配成 YOLO11 callback。"""

    if request.savepoint_callback is None:
        return None

    def on_yolo11_savepoint(savepoint: Yolo11SegmentationTrainingSavePoint) -> None:
        request.savepoint_callback(savepoint)

    return on_yolo11_savepoint


def _convert_yolo11_control_command(
    command: _TrainingControlCommandLike,
) -> Yolo11SegmentationTrainingControlCommand:
    """把平台训练控制命令转换为 YOLO11 控制命令。"""

    return Yolo11SegmentationTrainingControlCommand(
        save_checkpoint=command.save_checkpoint,
        pause_training=command.pause_training,
        terminate_training=command.terminate_training,
    )


__all__ = [
    "run_yolo11_segmentation_training_from_task_request",
]
