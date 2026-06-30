"""RF-DETR core 训练处理模块：`training.callbacks.ema`。"""

# ruff: noqa: E402

from __future__ import annotations

import math
import warnings
from copy import deepcopy
from typing import Any, Optional

import torch

from backend.service.application.models.rfdetr_core.training.lightning_bootstrap import (
    disable_lightning_model_summary_import,
)

disable_lightning_model_summary_import()

from pytorch_lightning import Callback, LightningModule, Trainer
from torch.optim.swa_utils import AveragedModel


class RFDETREMACallback(Callback):
    """RF-DETR core 类：`RFDETREMACallback`。"""

    def __init__(
        self,
        decay: float = 0.993,
        tau: int = 100,
        use_buffers: bool = True,
        update_interval_steps: int = 1,
    ) -> None:
        super().__init__()
        self._decay = decay
        self._tau = tau
        self._use_buffers = use_buffers
        self._update_interval_steps = max(1, int(update_interval_steps))

        self._average_model: Optional[AveragedModel] = None
        self._latest_update_step = 0
        self._latest_update_epoch = -1
        self._swapped_state_dict: Optional[dict[str, torch.Tensor]] = None
        self._pending_average_state_dict: Optional[dict[str, Any]] = None

    def _avg_fn(
        self,
        averaged_param: torch.Tensor,
        model_param: torch.Tensor,
        num_averaged: int,
    ) -> torch.Tensor:
        """执行 `_avg_fn`。
        
        参数：
        - `averaged_param`：传入的 `averaged_param` 参数。
        - `model_param`：传入的 `model_param` 参数。
        - `num_averaged`：传入的 `num_averaged` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        updates = num_averaged + 1
        if self._tau > 0:
            effective_decay = self._decay * (1 - math.exp(-updates / self._tau))
        else:
            effective_decay = self._decay
        return averaged_param * effective_decay + model_param * (1.0 - effective_decay)

    def setup(self, trainer: Trainer, pl_module: LightningModule, stage: str) -> None:
        """执行 `setup`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        - `stage`：传入的 `stage` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if stage != "fit":
            return

        self._average_model = AveragedModel(
            model=pl_module,
            device=pl_module.device,
            use_buffers=self._use_buffers,
            avg_fn=self._avg_fn,
        )
        self._average_model.eval()

        if self._pending_average_state_dict is not None:
            self._average_model.load_state_dict(self._pending_average_state_dict)
            self._pending_average_state_dict = None
        elif hasattr(pl_module, "_pending_legacy_ema_state"):
            legacy_ema_state = getattr(pl_module, "_pending_legacy_ema_state")
            if isinstance(legacy_ema_state, dict):
                incompatible = self._average_model.module.model.load_state_dict(legacy_ema_state, strict=False)
                if incompatible.missing_keys or incompatible.unexpected_keys:
                    warnings.warn(
                        "Legacy EMA checkpoint loaded with non-exact key match; "
                        f"missing={len(incompatible.missing_keys)} "
                        f"unexpected={len(incompatible.unexpected_keys)}.",
                        UserWarning,
                        stacklevel=2,
                    )
            delattr(pl_module, "_pending_legacy_ema_state")

    def should_update(
        self,
        step_idx: Optional[int] = None,
        epoch_idx: Optional[int] = None,
    ) -> bool:
        """执行 `should_update`。
        
        参数：
        - `step_idx`：传入的 `step_idx` 参数。
        - `epoch_idx`：传入的 `epoch_idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        return step_idx is not None or epoch_idx is not None

    def _swap_models(self, pl_module: LightningModule) -> None:
        """执行 `_swap_models`。
        
        参数：
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if self._average_model is None:
            return
        if self._swapped_state_dict is None:
            self._swapped_state_dict = deepcopy(pl_module.state_dict())
            pl_module.load_state_dict(self._average_model.module.state_dict(), strict=True)
            return
        pl_module.load_state_dict(self._swapped_state_dict, strict=True)
        self._swapped_state_dict = None

    def on_train_batch_end(
        self,
        trainer: Trainer,
        pl_module: LightningModule,
        outputs: Any,
        batch: Any,
        batch_idx: int,
    ) -> None:
        """执行 `on_train_batch_end`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        - `outputs`：传入的 `outputs` 参数。
        - `batch`：传入的 `batch` 参数。
        - `batch_idx`：传入的 `batch_idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if self._average_model is None:
            return
        step_idx = trainer.global_step - 1
        if trainer.global_step <= self._latest_update_step:
            return

        self._latest_update_step = trainer.global_step
        should_update_step = trainer.global_step % self._update_interval_steps == 0
        if should_update_step and self.should_update(step_idx=step_idx):
            self._average_model.update_parameters(pl_module)

    def on_train_epoch_end(self, trainer: Trainer, pl_module: LightningModule) -> None:
        """执行 `on_train_epoch_end`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if self._average_model is None:
            return
        if trainer.current_epoch > self._latest_update_epoch and self.should_update(epoch_idx=trainer.current_epoch):
            self._average_model.update_parameters(pl_module)
            self._latest_update_epoch = trainer.current_epoch

    def on_test_epoch_start(self, trainer: Trainer, pl_module: LightningModule) -> None:
        """执行 `on_test_epoch_start`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        self._swap_models(pl_module)

    def on_test_epoch_end(self, trainer: Trainer, pl_module: LightningModule) -> None:
        """执行 `on_test_epoch_end`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        self._swap_models(pl_module)

    def on_train_end(self, trainer: Trainer, pl_module: LightningModule) -> None:
        """执行 `on_train_end`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if self._average_model is not None:
            pl_module.load_state_dict(self._average_model.module.state_dict(), strict=True)
        self._swapped_state_dict = None

    def state_dict(self) -> dict[str, Any]:
        """执行 `state_dict`。
        
        返回：
        - 当前函数的执行结果。
        """
        state = {
            "latest_update_step": self._latest_update_step,
            "latest_update_epoch": self._latest_update_epoch,
        }
        if self._average_model is not None:
            state["average_model_state_dict"] = self._average_model.state_dict()
        return state

    def load_state_dict(self, state_dict: dict[str, Any]) -> None:
        """执行 `load_state_dict`。
        
        参数：
        - `state_dict`：传入的 `state_dict` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        self._latest_update_step = state_dict.get("latest_update_step", 0)
        self._latest_update_epoch = state_dict.get("latest_update_epoch", -1)
        self._pending_average_state_dict = state_dict.get("average_model_state_dict")

    def get_ema_model_state_dict(self) -> Optional[dict[str, torch.Tensor]]:
        """执行 `get_ema_model_state_dict`。
        
        返回：
        - 当前函数的执行结果。
        """
        if self._average_model is None or not hasattr(self._average_model.module, "model"):
            return None
        return {k: v.detach().clone() for k, v in self._average_model.module.model.state_dict().items()}


