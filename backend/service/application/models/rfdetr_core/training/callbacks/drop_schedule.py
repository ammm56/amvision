"""RF-DETR core 训练处理模块：`training.callbacks.drop_schedule`。"""

# ruff: noqa: E402

from __future__ import annotations

from typing import Any, Literal, Optional

import numpy as np

from backend.service.application.models.rfdetr_core.training.lightning_bootstrap import (
    disable_lightning_model_summary_import,
)

disable_lightning_model_summary_import()

from pytorch_lightning import Callback, LightningModule, Trainer

from backend.service.application.models.rfdetr_core.training.drop_schedule import drop_scheduler


class DropPathCallback(Callback):
    """RF-DETR core 类：`DropPathCallback`。"""

    def __init__(
        self,
        drop_path: float = 0.0,
        dropout: float = 0.0,
        cutoff_epoch: int = 0,
        mode: Literal["standard", "early", "late"] = "standard",
        schedule: Literal["constant", "linear"] = "constant",
        vit_encoder_num_layers: int = 12,
    ) -> None:
        super().__init__()
        self._drop_path = drop_path
        self._dropout = dropout
        self._cutoff_epoch = cutoff_epoch
        self._mode = mode
        self._schedule = schedule
        self._vit_encoder_num_layers = vit_encoder_num_layers

        self._dp_schedule: Optional[np.ndarray] = None
        self._do_schedule: Optional[np.ndarray] = None

    def on_train_start(self, trainer: Trainer, pl_module: LightningModule) -> None:
        """执行 `on_train_start`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        epochs: int = pl_module.train_config.epochs
        total_steps = int(trainer.estimated_stepping_batches)
        steps_per_epoch = max(1, total_steps // epochs)

        if self._drop_path > 0:
            self._dp_schedule = drop_scheduler(
                self._drop_path,
                epochs,
                steps_per_epoch,
                self._cutoff_epoch,
                self._mode,
                self._schedule,
            )

        if self._dropout > 0:
            self._do_schedule = drop_scheduler(
                self._dropout,
                epochs,
                steps_per_epoch,
                self._cutoff_epoch,
                self._mode,
                self._schedule,
            )

    def on_train_batch_start(
        self,
        trainer: Trainer,
        pl_module: LightningModule,
        batch: Any,
        batch_idx: int,
    ) -> None:
        """执行 `on_train_batch_start`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        - `batch`：传入的 `batch` 参数。
        - `batch_idx`：传入的 `batch_idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        step: int = trainer.global_step

        if self._dp_schedule is not None and step < len(self._dp_schedule):
            pl_module.model.update_drop_path(self._dp_schedule[step], self._vit_encoder_num_layers)

        if self._do_schedule is not None and step < len(self._do_schedule):
            pl_module.model.update_dropout(self._do_schedule[step])


