"""YOLO26 detection 完整训练循环。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolo26_core.training.checkpoint import (
    build_yolo26_detection_epoch_checkpoint_update,
)
from backend.service.application.models.yolo26_core.training.control import (
    Yolo26DetectionEpochControlDecision,
    resolve_yolo26_detection_epoch_control,
)
from backend.service.application.models.yolo26_core.training.epoch import (
    resolve_yolo26_detection_best_metric_update,
    serialize_yolo26_detection_best_metric_value,
    should_run_yolo26_detection_validation,
)
from backend.service.application.models.yolo26_core.training.runner import (
    Yolo26DetectionTrainingBatchProgress,
    run_yolo26_detection_training_epoch,
)
from backend.service.application.models.yolo26_core.training.pytorch_dataloader import (
    Yolo26DetectionDataLoaderBatch,
)
from backend.service.application.models.yolo26_core.training.savepoint import (
    Yolo26DetectionTrainingSavepointPayload,
    build_yolo26_detection_training_savepoint_payload,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloUltralyticsTrainingSchedule,
)


@dataclass(frozen=True)
class Yolo26DetectionTrainerEpochProgress:
    """描述 YOLO26 detection 单轮训练结束后的进度。"""

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
class Yolo26DetectionTrainingLoopResult:
    """描述 YOLO26 detection 完整训练循环结果。"""

    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes
    best_metric_name: str
    best_metric_value: float
    metrics_history: list[dict[str, object]]
    validation_history: list[dict[str, object]]
    evaluated_epochs: list[int]


class Yolo26DetectionTrainingPausedError(Exception):
    """表示 YOLO26 detection 训练在 epoch 边界暂停。"""

    def __init__(self, savepoint: Yolo26DetectionTrainingSavepointPayload) -> None:
        """保存暂停时需要交给应用层登记的 savepoint。"""

        super().__init__("YOLO26 detection 训练已暂停")
        self.savepoint = savepoint


class Yolo26DetectionTrainingTerminatedError(Exception):
    """表示 YOLO26 detection 训练在 epoch 边界终止。"""


def run_yolo26_detection_training_loop(
    *,
    torch_module: Any,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any,
    training_schedule: YoloUltralyticsTrainingSchedule | None,
    ema: Any | None,
    train_samples: tuple[Any, ...],
    validation_samples: tuple[Any, ...],
    batch_size: int,
    input_size: tuple[int, int],
    max_epochs: int,
    resume_epoch: int,
    initial_global_iteration: int,
    total_iterations: int,
    autocast_context: Callable[[], Any],
    build_batch: Callable[[list[Any], tuple[Any, ...], int], tuple[Any, tuple[Any, ...]]],
    unwrap_outputs: Callable[[Any], dict[str, Any]],
    compute_loss: Callable[..., dict[str, Any]],
    evaluate_model: Callable[[], dict[str, object]],
    grad_clip_norm: float,
    category_names: tuple[str, ...],
    model_scale: str,
    precision: str,
    validation_split_name: str | None,
    evaluation_interval: int,
    evaluation_confidence_threshold: float | None,
    evaluation_nms_threshold: float | None,
    learning_rate: float,
    weight_decay: float,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    min_lr_ratio: float,
    warm_start_summary: dict[str, object],
    implementation_mode: str,
    augmentation_options: dict[str, object] | None,
    has_validation: bool,
    best_metric_name: str,
    best_metric_value: float,
    metrics_history: list[dict[str, object]],
    validation_history: list[dict[str, object]],
    evaluated_epochs: list[int],
    previous_best_checkpoint_bytes: bytes,
    training_dataloader_factory: Callable[
        [int],
        Iterable[Yolo26DetectionDataLoaderBatch],
    ]
    | None = None,
    device: str | None = None,
    runtime_precision: str = "fp32",
    batch_callback: Callable[[Yolo26DetectionTrainingBatchProgress], None]
    | None = None,
    epoch_callback: Callable[
        [Yolo26DetectionTrainerEpochProgress],
        Yolo26DetectionEpochControlDecision | None,
    ]
    | None = None,
    savepoint_callback: Callable[[Yolo26DetectionTrainingSavepointPayload], None]
    | None = None,
) -> Yolo26DetectionTrainingLoopResult:
    """执行 YOLO26 detection 从 resume epoch 到 max epoch 的完整训练循环。"""

    global_iteration = int(initial_global_iteration)
    latest_checkpoint_bytes = b""
    best_checkpoint_bytes = previous_best_checkpoint_bytes
    current_best_metric_value = float(best_metric_value)

    for epoch in range(int(resume_epoch) + 1, int(max_epochs) + 1):
        epoch_result = run_yolo26_detection_training_epoch(
            torch_module=torch_module,
            model=model,
            samples=train_samples,
            batch_size=batch_size,
            input_size=input_size,
            epoch=epoch,
            max_epochs=max_epochs,
            global_iteration=global_iteration,
            total_iterations=total_iterations,
            optimizer=optimizer,
            scaler=scaler,
            training_schedule=training_schedule,
            autocast_context=autocast_context,
            build_batch=build_batch,
            unwrap_outputs=unwrap_outputs,
            compute_loss=compute_loss,
            grad_clip_norm=grad_clip_norm,
            ema=ema,
            dataloader_batches=(
                training_dataloader_factory(epoch)
                if training_dataloader_factory is not None
                else None
            ),
            device=device,
            runtime_precision=runtime_precision,
            batch_callback=batch_callback,
        )
        global_iteration = epoch_result.global_iteration
        train_metrics = dict(epoch_result.train_metrics)
        train_metrics["epoch"] = epoch
        metrics_history.append(train_metrics)

        validation_snapshot, validation_metrics, current_metric_value = (
            _run_yolo26_epoch_validation(
                epoch=epoch,
                max_epochs=max_epochs,
                evaluation_interval=evaluation_interval,
                validation_sample_count=len(validation_samples),
                best_metric_name=best_metric_name,
                evaluate_model=evaluate_model,
                validation_history=validation_history,
                evaluated_epochs=evaluated_epochs,
            )
        )
        validation_ran = validation_snapshot is not None
        best_metric_update = resolve_yolo26_detection_best_metric_update(
            validation_ran=validation_ran,
            current_metric_value=current_metric_value,
            train_loss=float(train_metrics["loss"]),
            best_metric_value=current_best_metric_value,
        )
        improved_best = best_metric_update.improved
        candidate_best_metric_value = best_metric_update.candidate_value

        scheduler.step()
        checkpoint_update = build_yolo26_detection_epoch_checkpoint_update(
            torch_module=torch_module,
            model=model,
            ema_model=getattr(ema, "model", None),
            ema_updates=getattr(ema, "updates", None),
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            model_type="yolo26",
            model_scale=model_scale,
            category_names=category_names,
            input_size=input_size,
            batch_size=batch_size,
            max_epochs=max_epochs,
            epoch=epoch,
            precision=precision,
            validation_split_name=validation_split_name,
            evaluation_interval=evaluation_interval,
            evaluation_confidence_threshold=(
                evaluation_confidence_threshold if has_validation else None
            ),
            evaluation_nms_threshold=(
                evaluation_nms_threshold if has_validation else None
            ),
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            class_loss_weight=class_loss_weight,
            box_loss_weight=box_loss_weight,
            dfl_loss_weight=dfl_loss_weight,
            assign_topk=assign_topk,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            min_lr_ratio=min_lr_ratio,
            grad_clip_norm=grad_clip_norm,
            metrics_history=metrics_history,
            validation_history=validation_history,
            evaluated_epochs=tuple(evaluated_epochs),
            warm_start_summary=warm_start_summary,
            implementation_mode=implementation_mode,
            augmentation_options=augmentation_options,
            best_metric_name=best_metric_name,
            candidate_best_metric_value=candidate_best_metric_value,
            previous_best_checkpoint_bytes=best_checkpoint_bytes,
            improved_best=improved_best,
        )
        latest_checkpoint_bytes = checkpoint_update.latest_checkpoint_bytes
        best_checkpoint_bytes = checkpoint_update.best_checkpoint_bytes
        current_best_metric_value = checkpoint_update.best_metric_value

        control_decision = _resolve_yolo26_epoch_control_decision(
            epoch_callback=epoch_callback,
            epoch=epoch,
            max_epochs=max_epochs,
            evaluation_interval=evaluation_interval,
            validation_ran=validation_ran,
            evaluated_epochs=tuple(evaluated_epochs),
            train_metrics=train_metrics,
            validation_metrics=validation_metrics,
            validation_snapshot=validation_snapshot,
            best_metric_name=best_metric_name,
            current_metric_value=current_metric_value,
            best_metric_value=current_best_metric_value,
            has_validation=has_validation,
            metrics_history=metrics_history,
        )
        if control_decision.save_checkpoint:
            savepoint = build_yolo26_detection_training_savepoint_payload(
                epoch=epoch,
                latest_checkpoint_bytes=latest_checkpoint_bytes,
                best_checkpoint_bytes=best_checkpoint_bytes,
                best_metric_name=best_metric_name,
                best_metric_value=current_best_metric_value,
                has_validation=has_validation,
            )
            if savepoint_callback is not None:
                savepoint_callback(savepoint)
            if control_decision.pause_training:
                raise Yolo26DetectionTrainingPausedError(savepoint)
        if control_decision.terminate_training:
            raise Yolo26DetectionTrainingTerminatedError()

    if not best_checkpoint_bytes:
        best_checkpoint_bytes = latest_checkpoint_bytes
    return Yolo26DetectionTrainingLoopResult(
        latest_checkpoint_bytes=latest_checkpoint_bytes,
        best_checkpoint_bytes=best_checkpoint_bytes,
        best_metric_name=best_metric_name,
        best_metric_value=_normalize_yolo26_final_best_metric_value(
            has_validation=has_validation,
            best_metric_value=current_best_metric_value,
        ),
        metrics_history=metrics_history,
        validation_history=validation_history,
        evaluated_epochs=evaluated_epochs,
    )


def _run_yolo26_epoch_validation(
    *,
    epoch: int,
    max_epochs: int,
    evaluation_interval: int,
    validation_sample_count: int,
    best_metric_name: str,
    evaluate_model: Callable[[], dict[str, object]],
    validation_history: list[dict[str, object]],
    evaluated_epochs: list[int],
) -> tuple[dict[str, object] | None, dict[str, float], float | None]:
    """按 YOLO26 detection epoch 规则执行一次可选 validation。"""

    validation_ran = should_run_yolo26_detection_validation(
        epoch=epoch,
        max_epochs=max_epochs,
        evaluation_interval=evaluation_interval,
        validation_sample_count=validation_sample_count,
    )
    if not validation_ran:
        return None, {}, None
    validation_snapshot = evaluate_model()
    validation_history.append(validation_snapshot)
    validation_metrics = {
        "loss": float(validation_snapshot["loss"]),
        "map50": float(validation_snapshot["map50"]),
        "map50_95": float(validation_snapshot["map50_95"]),
    }
    evaluated_epochs.append(epoch)
    return validation_snapshot, validation_metrics, validation_metrics[best_metric_name]


def _resolve_yolo26_epoch_control_decision(
    *,
    epoch_callback: Callable[
        [Yolo26DetectionTrainerEpochProgress],
        Yolo26DetectionEpochControlDecision | None,
    ]
    | None,
    epoch: int,
    max_epochs: int,
    evaluation_interval: int,
    validation_ran: bool,
    evaluated_epochs: tuple[int, ...],
    train_metrics: dict[str, float],
    validation_metrics: dict[str, float],
    validation_snapshot: dict[str, object] | None,
    best_metric_name: str,
    current_metric_value: float | None,
    best_metric_value: float,
    has_validation: bool,
    metrics_history: list[dict[str, object]],
) -> Yolo26DetectionEpochControlDecision:
    """把应用层 epoch callback 转换成 YOLO26 core 控制决策。"""

    if epoch_callback is None:
        return resolve_yolo26_detection_epoch_control(
            save_checkpoint_requested=False,
            pause_training_requested=False,
            terminate_training_requested=False,
        )
    control_decision = epoch_callback(
        Yolo26DetectionTrainerEpochProgress(
            epoch=epoch,
            max_epochs=max_epochs,
            evaluation_interval=evaluation_interval,
            validation_ran=validation_ran,
            evaluated_epochs=evaluated_epochs,
            train_metrics=train_metrics,
            validation_metrics=validation_metrics,
            train_metrics_snapshot={
                "history": metrics_history,
                "final_metrics": train_metrics,
            },
            validation_snapshot=validation_snapshot,
            current_metric_name=best_metric_name,
            current_metric_value=current_metric_value,
            best_metric_name=best_metric_name,
            best_metric_value=serialize_yolo26_detection_best_metric_value(
                has_validation=has_validation,
                best_metric_value=best_metric_value,
            ),
        )
    )
    if control_decision is None:
        return resolve_yolo26_detection_epoch_control(
            save_checkpoint_requested=False,
            pause_training_requested=False,
            terminate_training_requested=False,
        )
    return control_decision


def _normalize_yolo26_final_best_metric_value(
    *, has_validation: bool, best_metric_value: float
) -> float:
    """把 YOLO26 detection 内部 best metric 哨兵值转成最终结果值。"""

    if has_validation and best_metric_value == float("-inf"):
        return 0.0
    if not has_validation and best_metric_value == float("inf"):
        return 0.0
    return float(best_metric_value)


__all__ = [
    "Yolo26DetectionTrainerEpochProgress",
    "Yolo26DetectionTrainingLoopResult",
    "Yolo26DetectionTrainingPausedError",
    "Yolo26DetectionTrainingTerminatedError",
    "run_yolo26_detection_training_loop",
]
