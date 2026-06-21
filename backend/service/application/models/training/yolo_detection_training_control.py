"""YOLO detection 训练控制 DTO。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class YoloDetectionTrainingBatchProgress:
    """描述单个训练 batch 完成后的进度快照。"""

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
class YoloDetectionTrainingEpochProgress:
    """描述单轮训练结束后的进度快照。"""

    epoch: int
    max_epochs: int
    evaluation_interval: int
    validation_ran: bool
    evaluated_epochs: tuple[int, ...]
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    train_metrics_snapshot: dict[str, object]
    validation_snapshot: dict[str, object] | None
    current_metric_name: str
    current_metric_value: float | None
    best_metric_name: str
    best_metric_value: float | None


@dataclass(frozen=True)
class YoloDetectionTrainingControlCommand:
    """描述单轮训练结束后由上层返回给训练循环的控制命令。"""

    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


@dataclass(frozen=True)
class YoloDetectionTrainingSavePoint:
    """描述训练在某个 epoch 边界导出的可恢复 savepoint。"""

    epoch: int
    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes | None = None
    best_metric_name: str = ""
    best_metric_value: float | None = None


class YoloDetectionTrainingPausedError(Exception):
    """表示 detection 训练在 epoch 边界保存后进入 paused 状态。"""

    def __init__(self, savepoint: YoloDetectionTrainingSavePoint) -> None:
        """初始化 paused 异常并携带可恢复 savepoint。"""

        super().__init__("yolo detection training paused")
        self.savepoint = savepoint


class YoloDetectionTrainingTerminatedError(Exception):
    """表示 detection 训练在 epoch 边界按请求终止。"""

    def __init__(self) -> None:
        """初始化 terminated 异常。"""

        super().__init__("yolo detection training terminated")


__all__ = [
    "YoloDetectionTrainingBatchProgress",
    "YoloDetectionTrainingControlCommand",
    "YoloDetectionTrainingEpochProgress",
    "YoloDetectionTrainingPausedError",
    "YoloDetectionTrainingSavePoint",
    "YoloDetectionTrainingTerminatedError",
]
