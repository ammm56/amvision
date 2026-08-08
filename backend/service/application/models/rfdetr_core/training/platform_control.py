"""RF-DETR Lightning 训练循环与平台控制面的连接层。"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from backend.service.domain.models.model_task_types import (
    SEGMENTATION_TASK_TYPE,
    ModelTaskType,
)


_MAX_PROGRESS_COUNTER = (1 << 63) - 1


@dataclass(frozen=True)
class RfdetrPlatformBatchProgress:
    """描述 RF-DETR 真实训练 batch 完成后的进度。"""

    epoch: int
    max_epochs: int
    iteration: int
    max_iterations: int
    global_iteration: int
    total_iterations: int
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class RfdetrPlatformEpochProgress:
    """描述 RF-DETR 真实训练 epoch 完成后的进度。"""

    epoch: int
    max_epochs: int
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class RfdetrPlatformTrainingControlCommand:
    """描述平台在 epoch 边界返回的训练控制命令。"""

    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


@dataclass(frozen=True)
class RfdetrPlatformTrainingSavePoint:
    """描述已从临时训练目录完整读取出的可持久化保存点。"""

    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes | None
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float


class RfdetrPlatformTrainingControlSignal(RuntimeError):
    """在 Lightning hook 内请求安全退出当前训练循环。"""

    def __init__(
        self,
        *,
        status: Literal["paused", "terminated"],
        savepoint: RfdetrPlatformTrainingSavePoint,
    ) -> None:
        """保存中断状态和已生成的 checkpoint，避免临时目录清理后丢失。"""

        super().__init__(f"RF-DETR training {status}")
        self.status = status
        self.savepoint = savepoint


class _RfdetrPlatformTrainingCallbackMixin:
    """在真实 Lightning batch/epoch hook 中回写进度并执行控制命令。"""

    def __init__(
        self,
        *,
        task_type: ModelTaskType,
        output_dir: Path,
        max_epochs: int,
        batch_callback: Callable[[RfdetrPlatformBatchProgress], None] | None,
        epoch_callback: Callable[
            [RfdetrPlatformEpochProgress],
            RfdetrPlatformTrainingControlCommand | None,
        ]
        | None,
        savepoint_callback: Callable[[RfdetrPlatformTrainingSavePoint], None]
        | None,
    ) -> None:
        """初始化平台 callback；所有回调均在训练 worker 所在线程顺序执行。"""

        self.task_type = task_type
        self.output_dir = output_dir
        self.max_epochs = max(1, int(max_epochs))
        self.batch_callback = batch_callback
        self.epoch_callback = epoch_callback
        self.savepoint_callback = savepoint_callback

    def on_train_batch_end(
        self,
        trainer: Any,
        pl_module: Any,
        outputs: Any,
        batch: Any,
        batch_idx: int,
    ) -> None:
        """在每个真实 batch 完成后发送不持有 tensor 的标量进度。"""

        del pl_module, batch
        if self.batch_callback is None:
            return
        max_iterations = _resolve_positive_counter(
            getattr(trainer, "num_training_batches", None),
            fallback=max(1, int(batch_idx) + 1),
        )
        iteration = min(max_iterations, max(1, int(batch_idx) + 1))
        global_iteration = _resolve_positive_counter(
            getattr(trainer, "global_step", None),
            fallback=iteration,
        )
        total_iterations = min(
            _MAX_PROGRESS_COUNTER,
            self.max_epochs * max_iterations,
        )
        metrics = _extract_train_metrics(trainer=trainer, outputs=outputs)
        self.batch_callback(
            RfdetrPlatformBatchProgress(
                epoch=max(0, int(getattr(trainer, "current_epoch", 0))),
                max_epochs=self.max_epochs,
                iteration=iteration,
                max_iterations=max_iterations,
                global_iteration=min(global_iteration, total_iterations),
                total_iterations=total_iterations,
                learning_rate=_resolve_learning_rate(trainer),
                train_metrics=metrics,
            )
        )

    def on_train_epoch_end(self, trainer: Any, pl_module: Any) -> None:
        """在真实 epoch 边界读取控制命令并安全保存、暂停或终止。"""

        del pl_module
        if self.epoch_callback is None:
            return
        epoch = max(0, int(getattr(trainer, "current_epoch", 0)))
        learning_rate = _resolve_learning_rate(trainer)
        train_metrics = _extract_train_metrics(trainer=trainer, outputs=None)
        command = self.epoch_callback(
            RfdetrPlatformEpochProgress(
                epoch=epoch,
                max_epochs=self.max_epochs,
                learning_rate=learning_rate,
                train_metrics=train_metrics,
            )
        )
        if command is None:
            return
        needs_checkpoint = bool(
            command.save_checkpoint
            or command.pause_training
            or command.terminate_training
        )
        if not needs_checkpoint:
            return
        savepoint = self._save_checkpoint(
            trainer=trainer,
            epoch=epoch,
            learning_rate=learning_rate,
            train_metrics=train_metrics,
        )
        if self.savepoint_callback is not None:
            self.savepoint_callback(savepoint)
        if command.terminate_training:
            raise RfdetrPlatformTrainingControlSignal(
                status="terminated",
                savepoint=savepoint,
            )
        if command.pause_training:
            raise RfdetrPlatformTrainingControlSignal(
                status="paused",
                savepoint=savepoint,
            )

    def _save_checkpoint(
        self,
        *,
        trainer: Any,
        epoch: int,
        learning_rate: float,
        train_metrics: dict[str, float],
    ) -> RfdetrPlatformTrainingSavePoint:
        """保存完整 Lightning 恢复状态并在临时目录销毁前读入内存。"""

        self.output_dir.mkdir(parents=True, exist_ok=True)
        latest_checkpoint_path = self.output_dir / "last.ckpt"
        save_checkpoint = getattr(trainer, "save_checkpoint", None)
        if not callable(save_checkpoint):
            raise RuntimeError("RF-DETR Lightning trainer 不支持保存 checkpoint")
        save_checkpoint(str(latest_checkpoint_path))
        if not latest_checkpoint_path.is_file():
            raise RuntimeError("RF-DETR Lightning trainer 未生成 latest checkpoint")

        validation_metrics = _extract_validation_metrics(trainer)
        best_metric_name, best_metric_value = _resolve_best_metric(
            task_type=self.task_type,
            validation_metrics=validation_metrics,
        )
        return RfdetrPlatformTrainingSavePoint(
            latest_checkpoint_bytes=latest_checkpoint_path.read_bytes(),
            # 中间保存点只需要完整 latest 恢复状态。此处不再同时读取大型 best
            # 权重，避免 save/pause 时在内存中并存两份 checkpoint。
            best_checkpoint_bytes=None,
            train_metrics=train_metrics,
            validation_metrics=validation_metrics,
            best_metric_value=best_metric_value,
            best_metric_name=best_metric_name,
            epoch=epoch,
            learning_rate=learning_rate,
        )


def build_rfdetr_platform_training_callback(
    *,
    task_type: ModelTaskType,
    output_dir: Path,
    max_epochs: int,
    batch_callback: Callable[[RfdetrPlatformBatchProgress], None] | None,
    epoch_callback: Callable[
        [RfdetrPlatformEpochProgress],
        RfdetrPlatformTrainingControlCommand | None,
    ]
    | None,
    savepoint_callback: Callable[[RfdetrPlatformTrainingSavePoint], None] | None,
) -> Any:
    """延迟导入 Lightning 并构建符合其 Callback 类型检查的实例。"""

    from pytorch_lightning import Callback

    class RfdetrPlatformTrainingCallback(
        _RfdetrPlatformTrainingCallbackMixin,
        Callback,
    ):
        """本次训练使用的 Lightning callback 实例类型。"""

    return RfdetrPlatformTrainingCallback(
        task_type=task_type,
        output_dir=output_dir,
        max_epochs=max_epochs,
        batch_callback=batch_callback,
        epoch_callback=epoch_callback,
        savepoint_callback=savepoint_callback,
    )


def _resolve_positive_counter(value: object, *, fallback: int) -> int:
    """把 Lightning 可能返回的 inf、tensor 或异常计数收敛到 int64 范围。"""

    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return min(_MAX_PROGRESS_COUNTER, max(1, int(fallback)))
    if not math.isfinite(numeric) or numeric <= 0:
        return min(_MAX_PROGRESS_COUNTER, max(1, int(fallback)))
    return min(_MAX_PROGRESS_COUNTER, max(1, int(numeric)))


def _extract_train_metrics(*, trainer: Any, outputs: Any) -> dict[str, float]:
    """提取训练标量并立即 detach，避免进度回调持有计算图。"""

    metrics = {
        key: value
        for key, value in _tensor_mapping_to_float_dict(
            getattr(trainer, "callback_metrics", {})
        ).items()
        if key.startswith("train/") or key.startswith("train_")
    }
    if isinstance(outputs, Mapping):
        output_metrics = _tensor_mapping_to_float_dict(outputs)
        for key, value in output_metrics.items():
            metrics.setdefault(str(key), value)
    elif outputs is not None:
        scalar = _as_finite_float(outputs)
        if scalar is not None:
            metrics.setdefault("loss", scalar)
    return metrics


def _extract_validation_metrics(trainer: Any) -> dict[str, float]:
    """提取当前 epoch 已产生的 validation/test 标量。"""

    return {
        key: value
        for key, value in _tensor_mapping_to_float_dict(
            getattr(trainer, "callback_metrics", {})
        ).items()
        if key.startswith("val/") or key.startswith("test/")
    }


def _tensor_mapping_to_float_dict(payload: object) -> dict[str, float]:
    """把指标映射转换为有限 float，拒绝 NaN/Inf 污染任务状态。"""

    if not isinstance(payload, Mapping):
        return {}
    result: dict[str, float] = {}
    for key, value in payload.items():
        scalar = _as_finite_float(value)
        if scalar is not None:
            result[str(key)] = scalar
    return result


def _as_finite_float(value: object) -> float | None:
    """从普通数值或单元素 tensor 中读取有限 float。"""

    try:
        if hasattr(value, "detach"):
            value = value.detach().cpu().item()
        scalar = float(value)
    except (AttributeError, TypeError, ValueError, RuntimeError, OverflowError):
        return None
    return scalar if math.isfinite(scalar) else None


def _resolve_learning_rate(trainer: Any) -> float:
    """从实际 optimizer 读取当前学习率。"""

    optimizers = getattr(trainer, "optimizers", None)
    if not isinstance(optimizers, (list, tuple)) or not optimizers:
        return 0.0
    param_groups = getattr(optimizers[0], "param_groups", None)
    if not isinstance(param_groups, list) or not param_groups:
        return 0.0
    learning_rate = _as_finite_float(param_groups[0].get("lr"))
    return learning_rate if learning_rate is not None else 0.0


def _resolve_best_metric(
    *,
    task_type: ModelTaskType,
    validation_metrics: dict[str, float],
) -> tuple[str, float]:
    """从当前验证指标解析保存点的主指标。"""

    candidates = (
        ("val/segm_mAP_50_95", "val/mAP_50_95")
        if task_type == SEGMENTATION_TASK_TYPE
        else ("val/mAP_50_95",)
    )
    for metric_name in candidates:
        if metric_name in validation_metrics:
            return metric_name, validation_metrics[metric_name]
    return candidates[0], 0.0


__all__ = [
    "RfdetrPlatformBatchProgress",
    "RfdetrPlatformEpochProgress",
    "RfdetrPlatformTrainingControlCommand",
    "RfdetrPlatformTrainingControlSignal",
    "RfdetrPlatformTrainingSavePoint",
    "build_rfdetr_platform_training_callback",
]
