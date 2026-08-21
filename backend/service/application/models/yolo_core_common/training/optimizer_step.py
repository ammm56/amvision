"""普通 YOLO 任务共用的梯度累积、warmup、AMP、裁剪和 EMA step。"""

from __future__ import annotations

import math
from typing import Any
import time

from backend.service.application.models.training.training_engine import (
    record_active_training_batch_stage_metrics,
)

from backend.service.application.models.yolo_core_common.training.ultralytics_schedule import (
    YoloUltralyticsTrainingSchedule,
    apply_yolo_ultralytics_warmup,
)


# PyTorch GradScaler 不保证 scale 始终大于等于 1。RLE 等高梯度分支可能
# 需要 sub-unit scale 才能让 FP16 中间 gradient 保持有限；在 1.0 处终止会
# 把仍可恢复的 batch 误判成永久数值错误。2^-16 对应 FP16 最小 subnormal
# 量级，在继续下降只会大量丢失有效 gradient 前保留明确的硬停止边界。
_MIN_RECOVERABLE_AMP_SCALE = 2.0**-16
_MAX_STALLED_AMP_SKIPPED_STEPS = 8


class YoloTrainingNumericalError(RuntimeError):
    """表示 loss 或 FP32 gradient 已出现 NaN/Inf，训练必须立即失败。"""


def require_yolo_successful_optimizer_step(
    *,
    successful_optimizer_steps: int,
    skipped_optimizer_steps: int,
    task_name: str,
) -> None:
    """拒绝没有发生任何参数更新却被登记为成功的训练结果。

    ``GradScaler`` 可以在 overflow 时跳过 optimizer step，这是正常的恢复机制；
    但一次完整训练如果始终没有成功 step，产出的 checkpoint 仍是初始权重，
    后续评估、注册和转换都没有业务意义，必须以数值错误结束。
    """

    successful_count = max(0, int(successful_optimizer_steps))
    if successful_count > 0:
        return
    raise YoloTrainingNumericalError(
        f"{str(task_name).strip() or 'YOLO'} 训练没有任何成功的 optimizer step "
        f"(successful_optimizer_steps={successful_count}, "
        f"amp_skipped_optimizer_steps={max(0, int(skipped_optimizer_steps))})"
    )


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
        self._batch_runtime_metrics: dict[str, float] = {}
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
        self._batch_runtime_metrics = {
            "gradient_accumulate": float(self.current_accumulate),
        }
        self._forward_started_at = time.perf_counter()
        return self.current_accumulate

    def record_batch_runtime_metrics(self, metrics: dict[str, float]) -> None:
        """补充当前 batch 的低开销诊断字段。"""

        self._batch_runtime_metrics.update(
            {
                str(name): float(value)
                for name, value in metrics.items()
                if isinstance(value, int | float)
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                and float(value) >= 0.0
            }
        )

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
            self.record_batch_runtime_metrics(
                {
                    "optimizer_step_attempted": 0.0,
                    "optimizer_step_succeeded": 0.0,
                    "optimizer_successful_steps": float(
                        self.successful_optimizer_steps
                    ),
                    "optimizer_skipped_steps": float(self.skipped_optimizer_steps),
                }
            )
            self._record_stage_metrics(
                forward_started_at=forward_started_at,
                backward_started_at=backward_started_at,
            )
            return False
        if self.scaler is not None:
            self.scaler.unscale_(self.optimizer)
        optimizer_step_succeeded = True
        amp_scale_before: float | None = None
        amp_scale_after: float | None = None
        nonfinite_gradient_parameters: tuple[str, ...] = ()
        if self.scaler is not None:
            try:
                self.torch.nn.utils.clip_grad_norm_(
                    self.model.parameters(),
                    self.grad_clip_norm if self.grad_clip_norm > 0 else float("inf"),
                    error_if_nonfinite=True,
                )
                gradients_are_finite = True
            except RuntimeError:
                # ``error_if_nonfinite=False`` 会继续执行裁剪；Inf * 0 会把
                # 原本有限的 gradient 一并改成 NaN，导致无法定位首个源头。
                # 异常路径先保留原始 gradient，再记录具体参数名供真实训练诊断。
                gradients_are_finite = False
                nonfinite_gradient_parameters = (
                    self._find_nonfinite_gradient_parameters()
                )
        else:
            try:
                self.torch.nn.utils.clip_grad_norm_(
                    self.model.parameters(),
                    self.grad_clip_norm if self.grad_clip_norm > 0 else float("inf"),
                    error_if_nonfinite=True,
                )
            except RuntimeError as error:
                nonfinite_gradient_parameters = (
                    self._find_nonfinite_gradient_parameters()
                )
                raise YoloTrainingNumericalError(
                    "YOLO 训练产生非有限 FP32 gradient "
                    f"(global_iteration={int(iteration_index)}, "
                    f"nonfinite_gradient_parameters="
                    f"{self._format_gradient_parameter_names(nonfinite_gradient_parameters)})"
                ) from error
        if self.scaler is not None:
            scale_before_step = float(self.scaler.get_scale())
            self.scaler.step(self.optimizer)
            self.scaler.update()
            scale_after_step = float(self.scaler.get_scale())
            amp_scale_before = scale_before_step
            amp_scale_after = scale_after_step
            optimizer_step_succeeded = (
                gradients_are_finite and scale_after_step >= scale_before_step
            )
        else:
            self.optimizer.step()
        consecutive_overflow_error: YoloTrainingNumericalError | None = None
        if optimizer_step_succeeded:
            self.successful_optimizer_steps += 1
            self.consecutive_skipped_optimizer_steps = 0
        else:
            self.skipped_optimizer_steps += 1
            self.consecutive_skipped_optimizer_steps += 1
            scale_below_recoverable_minimum = bool(
                amp_scale_after is not None
                and amp_scale_after < _MIN_RECOVERABLE_AMP_SCALE
            )
            scale_reduction_stalled = bool(
                amp_scale_before is not None
                and amp_scale_after is not None
                and amp_scale_after >= amp_scale_before
                and self.consecutive_skipped_optimizer_steps
                >= _MAX_STALLED_AMP_SKIPPED_STEPS
            )
            if scale_below_recoverable_minimum or scale_reduction_stalled:
                consecutive_overflow_error = YoloTrainingNumericalError(
                    "YOLO AMP 连续产生非有限 gradient，GradScaler 已无法恢复 "
                    f"(global_iteration={int(iteration_index)}, "
                    f"consecutive_skipped_steps="
                    f"{self.consecutive_skipped_optimizer_steps}, "
                    f"scale_before={amp_scale_before}, "
                    f"scale_after={amp_scale_after}, "
                    f"nonfinite_gradient_parameters="
                    f"{self._format_gradient_parameter_names(nonfinite_gradient_parameters)})"
                )
        optimizer_metrics = {
            "optimizer_step_attempted": 1.0,
            "optimizer_step_succeeded": float(optimizer_step_succeeded),
            "optimizer_successful_steps": float(self.successful_optimizer_steps),
            "optimizer_skipped_steps": float(self.skipped_optimizer_steps),
            "optimizer_consecutive_skipped_steps": float(
                self.consecutive_skipped_optimizer_steps
            ),
        }
        if amp_scale_before is not None:
            optimizer_metrics["amp_scale_before"] = amp_scale_before
        if amp_scale_after is not None:
            optimizer_metrics["amp_scale_after"] = amp_scale_after
        self.record_batch_runtime_metrics(optimizer_metrics)
        if self.ema is not None and optimizer_step_succeeded:
            self.ema.update(self.model)
        self.optimizer.zero_grad(set_to_none=True)
        self.last_optimizer_step_iteration = int(iteration_index)
        self._record_stage_metrics(
            forward_started_at=forward_started_at,
            backward_started_at=backward_started_at,
        )
        if consecutive_overflow_error is not None:
            raise consecutive_overflow_error
        return optimizer_step_succeeded

    def _find_nonfinite_gradient_parameters(self) -> tuple[str, ...]:
        """返回含 NaN/Inf gradient 的参数名，限制数量避免错误文本失控。"""

        names: list[str] = []
        for name, parameter in self.model.named_parameters():
            gradient = parameter.grad
            if gradient is None:
                continue
            if not bool(self.torch.isfinite(gradient).all().item()):
                names.append(str(name))
                if len(names) >= 16:
                    break
        return tuple(names)

    @staticmethod
    def _format_gradient_parameter_names(names: tuple[str, ...]) -> str:
        """把异常参数名压缩成稳定的单行诊断文本。"""

        return "[" + ",".join(names) + "]"

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
                **self._batch_runtime_metrics,
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

    def require_successful_optimizer_step(self, *, task_name: str) -> None:
        """在训练结果落盘和模型注册前确认至少完成过一次参数更新。"""

        require_yolo_successful_optimizer_step(
            successful_optimizer_steps=self.successful_optimizer_steps,
            skipped_optimizer_steps=self.skipped_optimizer_steps,
            task_name=task_name,
        )

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


__all__ = [
    "YoloTrainingNumericalError",
    "YoloUltralyticsOptimizerStep",
    "require_yolo_successful_optimizer_step",
]
