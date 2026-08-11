"""普通 YOLO 任务共用的梯度累积、warmup、AMP、裁剪和 EMA step。"""

from __future__ import annotations

from typing import Any
import time

from backend.service.application.models.training.training_engine import (
    record_active_training_batch_stage_metrics,
)

from backend.service.application.models.yolo_core_common.training.ultralytics_schedule import (
    YoloUltralyticsTrainingSchedule,
    apply_yolo_ultralytics_warmup,
)


class YoloTrainingNumericalError(RuntimeError):
    """表示 loss 或 FP32 gradient 已出现 NaN/Inf，训练必须立即失败。"""


class YoloUltralyticsOptimizerStep:
    """维护与 Ultralytics 对齐的跨 batch optimizer step 状态。"""

    def __init__(
        self,
        *,
        torch_module: Any,
        model: Any,
        optimizer: Any,
        scaler: Any | None,
        schedule: YoloUltralyticsTrainingSchedule,
        ema: Any | None,
        grad_clip_norm: float,
        initial_iteration: int = 0,
    ) -> None:
        """初始化 step 状态，并清空当前 optimizer 梯度。"""

        self.torch = torch_module
        self.model = model
        self.optimizer = optimizer
        self.scaler = scaler
        self.schedule = schedule
        self.ema = ema
        self.grad_clip_norm = max(0.0, float(grad_clip_norm))
        self.last_optimizer_step_iteration = max(0, int(initial_iteration))
        self.current_accumulate = max(1, int(schedule.accumulate))
        self.successful_optimizer_steps = 0
        self.skipped_optimizer_steps = 0
        self.consecutive_skipped_optimizer_steps = 0
        self.last_scheduler_optimizer_step_count = 0
        self._forward_started_at: float | None = None
        self.optimizer.zero_grad(set_to_none=True)

    def prepare_batch(
        self,
        *,
        iteration_index: int,
        epoch: int,
        batch_size: int,
    ) -> int:
        """在 forward 前应用 warmup，并返回当前梯度累积步数。"""

        self.current_accumulate = apply_yolo_ultralytics_warmup(
            optimizer=self.optimizer,
            schedule=self.schedule,
            iteration_index=max(0, int(iteration_index) - 1),
            epoch=max(1, int(epoch)),
            batch_size=max(1, int(batch_size)),
        )
        self._forward_started_at = time.perf_counter()
        return self.current_accumulate

    def backward_and_step(
        self,
        *,
        loss: Any,
        iteration_index: int,
        is_last_batch: bool,
    ) -> bool:
        """反传当前 loss，并在达到累积边界时执行 optimizer 和 EMA step。"""

        backward_started_at = time.perf_counter()
        forward_started_at = self._forward_started_at or backward_started_at
        self._ensure_finite_scalar_loss(loss, iteration_index=iteration_index)
        if self.scaler is not None:
            self.scaler.scale(loss).backward()
        else:
            loss.backward()
        should_step = (
            int(iteration_index) - self.last_optimizer_step_iteration
            >= self.current_accumulate
            or bool(is_last_batch)
        )
        if not should_step:
            self._record_stage_metrics(
                forward_started_at=forward_started_at,
                backward_started_at=backward_started_at,
            )
            return False
        if self.scaler is not None:
            self.scaler.unscale_(self.optimizer)
        optimizer_step_succeeded = True
        if self.scaler is not None:
            gradient_norm = self.torch.nn.utils.clip_grad_norm_(
                self.model.parameters(),
                self.grad_clip_norm if self.grad_clip_norm > 0 else float("inf"),
                error_if_nonfinite=False,
            )
            gradients_are_finite = bool(self.torch.isfinite(gradient_norm).item())
        else:
            try:
                self.torch.nn.utils.clip_grad_norm_(
                    self.model.parameters(),
                    self.grad_clip_norm if self.grad_clip_norm > 0 else float("inf"),
                    error_if_nonfinite=True,
                )
            except RuntimeError as error:
                raise YoloTrainingNumericalError(
                    "YOLO 训练产生非有限 FP32 gradient "
                    f"(global_iteration={int(iteration_index)})"
                ) from error
        if self.scaler is not None:
            scale_before_step = float(self.scaler.get_scale())
            self.scaler.step(self.optimizer)
            self.scaler.update()
            scale_after_step = float(self.scaler.get_scale())
            optimizer_step_succeeded = (
                gradients_are_finite and scale_after_step >= scale_before_step
            )
        else:
            self.optimizer.step()
        if optimizer_step_succeeded:
            self.successful_optimizer_steps += 1
            self.consecutive_skipped_optimizer_steps = 0
        else:
            self.skipped_optimizer_steps += 1
            self.consecutive_skipped_optimizer_steps += 1
        if self.ema is not None and optimizer_step_succeeded:
            self.ema.update(self.model)
        self.optimizer.zero_grad(set_to_none=True)
        self.last_optimizer_step_iteration = int(iteration_index)
        self._record_stage_metrics(
            forward_started_at=forward_started_at,
            backward_started_at=backward_started_at,
        )
        return optimizer_step_succeeded

    def _record_stage_metrics(
        self,
        *,
        forward_started_at: float,
        backward_started_at: float,
    ) -> None:
        """记录 host 提交和同步边界耗时，不主动同步 CUDA。"""

        completed_at = time.perf_counter()
        self._forward_started_at = None
        record_active_training_batch_stage_metrics(
            {
                "forward_loss_host_time_ms": (
                    backward_started_at - forward_started_at
                )
                * 1000.0,
                "backward_optimizer_host_time_ms": (
                    completed_at - backward_started_at
                )
                * 1000.0,
                "batch_compute_host_time_ms": (
                    completed_at - forward_started_at
                )
                * 1000.0,
            }
        )

    def step_scheduler_if_optimizer_updated(self, scheduler: Any) -> bool:
        """仅在模型真实更新后推进 epoch scheduler。

        AMP overflow 时 ``GradScaler.step`` 会有意跳过 optimizer。此时继续
        ``scheduler.step`` 会让学习率脱离真实优化步数，并触发 PyTorch 的
        step-order warning。该状态统一由 optimizer step 组件持有，避免每个
        task trainer 各自猜测 GradScaler 是否执行了更新。
        """

        if (
            self.successful_optimizer_steps
            <= self.last_scheduler_optimizer_step_count
        ):
            return False
        scheduler.step()
        self.last_scheduler_optimizer_step_count = self.successful_optimizer_steps
        return True

    def _ensure_finite_scalar_loss(
        self,
        loss: Any,
        *,
        iteration_index: int,
    ) -> None:
        """在反传前拒绝非标量或 NaN/Inf loss，避免污染模型和 checkpoint。"""

        detached = loss.detach()
        if int(detached.numel()) != 1:
            raise YoloTrainingNumericalError(
                "YOLO 训练 total loss 必须是标量 "
                f"(global_iteration={int(iteration_index)}, numel={int(detached.numel())})"
            )
        if not bool(self.torch.isfinite(detached).item()):
            raise YoloTrainingNumericalError(
                "YOLO 训练产生非有限 total loss "
                f"(global_iteration={int(iteration_index)}, value={float(detached.item())})"
            )


__all__ = ["YoloTrainingNumericalError", "YoloUltralyticsOptimizerStep"]
