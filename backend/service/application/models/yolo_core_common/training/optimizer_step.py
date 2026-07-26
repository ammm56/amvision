"""普通 YOLO 任务共用的梯度累积、warmup、AMP、裁剪和 EMA step。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.training.ultralytics_schedule import (
    YoloUltralyticsTrainingSchedule,
    apply_yolo_ultralytics_warmup,
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
        return self.current_accumulate

    def backward_and_step(
        self,
        *,
        loss: Any,
        iteration_index: int,
        is_last_batch: bool,
    ) -> bool:
        """反传当前 loss，并在达到累积边界时执行 optimizer 和 EMA step。"""

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
            return False
        if self.scaler is not None:
            self.scaler.unscale_(self.optimizer)
        if self.grad_clip_norm > 0:
            self.torch.nn.utils.clip_grad_norm_(
                self.model.parameters(),
                self.grad_clip_norm,
            )
        if self.scaler is not None:
            self.scaler.step(self.optimizer)
            self.scaler.update()
        else:
            self.optimizer.step()
        if self.ema is not None:
            self.ema.update(self.model)
        self.optimizer.zero_grad(set_to_none=True)
        self.last_optimizer_step_iteration = int(iteration_index)
        return True


__all__ = ["YoloUltralyticsOptimizerStep"]
