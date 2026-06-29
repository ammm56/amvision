"""YOLO11 detection 完整训练循环。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.models.support.distributed_training import (
    DdpTrainingContext,
)
from backend.service.application.models.yolo11_core.training.checkpoint import (
    build_yolo11_detection_epoch_checkpoint_update,
)
from backend.service.application.models.yolo11_core.training.control import (
    Yolo11DetectionEpochControlDecision,
    resolve_yolo11_detection_epoch_control,
)
from backend.service.application.models.yolo11_core.training.epoch import (
    resolve_yolo11_detection_best_metric_update,
    serialize_yolo11_detection_best_metric_value,
    should_run_yolo11_detection_validation,
)
from backend.service.application.models.yolo11_core.training.runner import (
    Yolo11DetectionTrainingBatchProgress,
    run_yolo11_detection_training_epoch,
)
from backend.service.application.models.yolo11_core.training.savepoint import (
    Yolo11DetectionTrainingSavepointPayload,
    build_yolo11_detection_training_savepoint_payload,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloUltralyticsTrainingSchedule,
)


@dataclass(frozen=True)
class Yolo11DetectionTrainerEpochProgress:
    """描述 YOLO11 detection 单轮训练结束后的进度。"""

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
class Yolo11DetectionTrainingLoopResult:
    """描述 YOLO11 detection 完整训练循环结果。"""

    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes
    best_metric_name: str
    best_metric_value: float
    metrics_history: list[dict[str, object]]
    validation_history: list[dict[str, object]]
    evaluated_epochs: list[int]


class Yolo11DetectionTrainingPausedError(Exception):
    """表示 YOLO11 detection 训练在 epoch 边界暂停。"""

    def __init__(self, savepoint: Yolo11DetectionTrainingSavepointPayload) -> None:
        """保存暂停时需要交给应用层登记的 savepoint。"""

        super().__init__("YOLO11 detection 训练已暂停")
        self.savepoint = savepoint


class Yolo11DetectionTrainingTerminatedError(Exception):
    """表示 YOLO11 detection 训练在 epoch 边界终止。"""


def run_yolo11_detection_training_loop(
    *,
    torch_module: Any,
    model: Any,
    checkpoint_model: Any | None = None,
    loss_model: Any | None = None,
    ema_model: Any | None = None,
    gradient_model: Any | None = None,
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
    batch_callback: Callable[[Yolo11DetectionTrainingBatchProgress], None]
    | None = None,
    epoch_callback: Callable[
        [Yolo11DetectionTrainerEpochProgress],
        Yolo11DetectionEpochControlDecision | None,
    ]
    | None = None,
    savepoint_callback: Callable[[Yolo11DetectionTrainingSavepointPayload], None]
    | None = None,
    ddp_context: DdpTrainingContext | None = None,
) -> Yolo11DetectionTrainingLoopResult:
    """执行 YOLO11 detection 从 resume epoch 到 max epoch 的完整训练循环。"""

    resolved_checkpoint_model = (
        checkpoint_model if checkpoint_model is not None else model
    )
    is_rank_zero = ddp_context is None or ddp_context.is_rank_zero
    global_iteration = int(initial_global_iteration)
    latest_checkpoint_bytes = b""
    best_checkpoint_bytes = previous_best_checkpoint_bytes
    current_best_metric_value = float(best_metric_value)

    for epoch in range(int(resume_epoch) + 1, int(max_epochs) + 1):
        epoch_result = run_yolo11_detection_training_epoch(
            torch_module=torch_module,
            model=model,
            loss_model=loss_model,
            ema_model=ema_model,
            gradient_model=gradient_model,
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
            ddp_context=ddp_context,
            batch_callback=batch_callback,
        )
        global_iteration = epoch_result.global_iteration
        train_metrics = dict(epoch_result.train_metrics)
        train_metrics["epoch"] = epoch
        metrics_history.append(train_metrics)

        validation_should_run = should_run_yolo11_detection_validation(
            epoch=epoch,
            max_epochs=max_epochs,
            evaluation_interval=evaluation_interval,
            validation_sample_count=len(validation_samples),
        )
        if validation_should_run and is_rank_zero:
            validation_snapshot, validation_metrics, current_metric_value = (
                _run_yolo11_epoch_validation(
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
        else:
            validation_snapshot, validation_metrics, current_metric_value = None, {}, None
        if validation_should_run:
            _barrier_yolo11_detection_ddp_rank(
                torch_module=torch_module,
                ddp_context=ddp_context,
            )
        validation_ran = validation_snapshot is not None
        if is_rank_zero:
            best_metric_update = resolve_yolo11_detection_best_metric_update(
                validation_ran=validation_ran,
                current_metric_value=current_metric_value,
                train_loss=float(train_metrics["loss"]),
                best_metric_value=current_best_metric_value,
            )
            improved_best = best_metric_update.improved
            candidate_best_metric_value = best_metric_update.candidate_value
        else:
            improved_best = False
            candidate_best_metric_value = current_best_metric_value

        scheduler.step()
        if is_rank_zero:
            checkpoint_update = build_yolo11_detection_epoch_checkpoint_update(
                torch_module=torch_module,
                model=resolved_checkpoint_model,
                ema_model=getattr(ema, "model", None),
                ema_updates=getattr(ema, "updates", None),
                optimizer=optimizer,
                scheduler=scheduler,
                scaler=scaler,
                model_type="yolo11",
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

        control_decision = (
            _resolve_yolo11_epoch_control_decision(
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
            if is_rank_zero
            else None
        )
        control_decision = _broadcast_yolo11_detection_epoch_control(
            torch_module=torch_module,
            ddp_context=ddp_context,
            control_decision=control_decision,
        )
        if control_decision.save_checkpoint:
            if not is_rank_zero:
                if control_decision.pause_training:
                    return _build_non_rank0_yolo11_detection_training_loop_result(
                        best_metric_name=best_metric_name,
                        best_metric_value=current_best_metric_value,
                        metrics_history=metrics_history,
                    )
                continue
            savepoint = build_yolo11_detection_training_savepoint_payload(
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
                raise Yolo11DetectionTrainingPausedError(savepoint)
        if control_decision.terminate_training:
            if not is_rank_zero:
                return _build_non_rank0_yolo11_detection_training_loop_result(
                    best_metric_name=best_metric_name,
                    best_metric_value=current_best_metric_value,
                    metrics_history=metrics_history,
                )
            raise Yolo11DetectionTrainingTerminatedError()

    if not is_rank_zero:
        return _build_non_rank0_yolo11_detection_training_loop_result(
            best_metric_name=best_metric_name,
            best_metric_value=current_best_metric_value,
            metrics_history=metrics_history,
        )
    if not best_checkpoint_bytes:
        best_checkpoint_bytes = latest_checkpoint_bytes
    return Yolo11DetectionTrainingLoopResult(
        latest_checkpoint_bytes=latest_checkpoint_bytes,
        best_checkpoint_bytes=best_checkpoint_bytes,
        best_metric_name=best_metric_name,
        best_metric_value=_normalize_yolo11_final_best_metric_value(
            has_validation=has_validation,
            best_metric_value=current_best_metric_value,
        ),
        metrics_history=metrics_history,
        validation_history=validation_history,
        evaluated_epochs=evaluated_epochs,
    )


def _run_yolo11_epoch_validation(
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
    """按 YOLO11 detection epoch 规则执行一次可选 validation。"""

    validation_ran = should_run_yolo11_detection_validation(
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


def _barrier_yolo11_detection_ddp_rank(
    *,
    torch_module: Any,
    ddp_context: DdpTrainingContext | None,
) -> None:
    """在 YOLO11 detection DDP rank 之间等待 rank0 完成 validation。"""

    if ddp_context is None or not ddp_context.is_distributed:
        return
    torch_module.distributed.barrier()


def _broadcast_yolo11_detection_epoch_control(
    *,
    torch_module: Any,
    ddp_context: DdpTrainingContext | None,
    control_decision: Yolo11DetectionEpochControlDecision | None,
) -> Yolo11DetectionEpochControlDecision:
    """把 rank0 的 epoch 控制命令广播到所有 YOLO11 detection rank。"""

    if ddp_context is None or not ddp_context.is_distributed:
        if control_decision is None:
            return resolve_yolo11_detection_epoch_control(
                save_checkpoint_requested=False,
                pause_training_requested=False,
                terminate_training_requested=False,
            )
        return control_decision
    objects = [control_decision if ddp_context.is_rank_zero else None]
    torch_module.distributed.broadcast_object_list(objects, src=0)
    broadcast_decision = objects[0]
    if isinstance(broadcast_decision, Yolo11DetectionEpochControlDecision):
        return broadcast_decision
    return resolve_yolo11_detection_epoch_control(
        save_checkpoint_requested=False,
        pause_training_requested=False,
        terminate_training_requested=False,
    )


def _build_non_rank0_yolo11_detection_training_loop_result(
    *,
    best_metric_name: str,
    best_metric_value: float,
    metrics_history: list[dict[str, object]],
) -> Yolo11DetectionTrainingLoopResult:
    """生成非 rank0 的空产物结果，避免重复写 checkpoint 和平台状态。"""

    return Yolo11DetectionTrainingLoopResult(
        latest_checkpoint_bytes=b"",
        best_checkpoint_bytes=b"",
        best_metric_name=best_metric_name,
        best_metric_value=float(best_metric_value),
        metrics_history=metrics_history,
        validation_history=[],
        evaluated_epochs=[],
    )


def _resolve_yolo11_epoch_control_decision(
    *,
    epoch_callback: Callable[
        [Yolo11DetectionTrainerEpochProgress],
        Yolo11DetectionEpochControlDecision | None,
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
) -> Yolo11DetectionEpochControlDecision:
    """把应用层 epoch callback 转换成 YOLO11 core 控制决策。"""

    if epoch_callback is None:
        return resolve_yolo11_detection_epoch_control(
            save_checkpoint_requested=False,
            pause_training_requested=False,
            terminate_training_requested=False,
        )
    control_decision = epoch_callback(
        Yolo11DetectionTrainerEpochProgress(
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
            best_metric_value=serialize_yolo11_detection_best_metric_value(
                has_validation=has_validation,
                best_metric_value=best_metric_value,
            ),
        )
    )
    if control_decision is None:
        return resolve_yolo11_detection_epoch_control(
            save_checkpoint_requested=False,
            pause_training_requested=False,
            terminate_training_requested=False,
        )
    return control_decision


def _normalize_yolo11_final_best_metric_value(
    *, has_validation: bool, best_metric_value: float
) -> float:
    """把 YOLO11 detection 内部 best metric 哨兵值转成最终结果值。"""

    if has_validation and best_metric_value == float("-inf"):
        return 0.0
    if not has_validation and best_metric_value == float("inf"):
        return 0.0
    return float(best_metric_value)


__all__ = [
    "Yolo11DetectionTrainerEpochProgress",
    "Yolo11DetectionTrainingLoopResult",
    "Yolo11DetectionTrainingPausedError",
    "Yolo11DetectionTrainingTerminatedError",
    "run_yolo11_detection_training_loop",
]
