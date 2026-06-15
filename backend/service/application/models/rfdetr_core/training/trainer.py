"""RF-DETR core 训练处理模块：`training.trainer`。"""

import warnings
from typing import Any

import torch
from pytorch_lightning import Trainer
from pytorch_lightning.callbacks import ModelCheckpoint, RichProgressBar, TQDMProgressBar
from pytorch_lightning.callbacks.progress.rich_progress import RichProgressBarTheme
from pytorch_lightning.loggers import CSVLogger, TensorBoardLogger
from pytorch_lightning.strategies import DDPStrategy as _DDPStrategy

try:
    from pytorch_lightning.strategies.launchers.multiprocessing import _MultiProcessingLauncher
except ImportError:  # pragma: no cover - exercised in unit tests via monkeypatch
    _MultiProcessingLauncher = None  # type: ignore[assignment]

from backend.service.application.models.rfdetr_core.config import ModelConfig, TrainConfig
from backend.service.application.models.rfdetr_core.training.callbacks import (
    BestModelCallback,
    DropPathCallback,
    RFDETREarlyStopping,
    RFDETREMACallback,
)
from backend.service.application.models.rfdetr_core.training.callbacks.coco_eval import COCOEvalCallback
from backend.service.application.models.rfdetr_core.utilities.logger import get_logger

_logger = get_logger()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
#
#


if _MultiProcessingLauncher is not None:

    class _InteractiveSpawnLauncher(_MultiProcessingLauncher):
        """RF-DETR core 类：`_InteractiveSpawnLauncher`。"""

        @property
        def is_interactive_compatible(self) -> bool:  # type: ignore[override]
            return True

else:
    _InteractiveSpawnLauncher = None


class _NotebookSpawnDDPStrategy(_DDPStrategy):
    """RF-DETR core 类：`_NotebookSpawnDDPStrategy`。"""

    def _configure_launcher(self) -> None:
        if self.cluster_environment is None:
            raise RuntimeError(
                "_NotebookSpawnDDPStrategy requires a cluster environment; "
                "ensure the strategy is initialised through PTL's Trainer."
            )
        if _InteractiveSpawnLauncher is None:
            raise RuntimeError(
                "Notebook spawn strategy requires "
                "pytorch_lightning.strategies.launchers.multiprocessing._MultiProcessingLauncher. "
                "Your installed PyTorch Lightning version changed this private API; "
                "pin/upgrade PTL to a compatible version in the supported >=2.6,<3 range."
            )
        self._launcher = _InteractiveSpawnLauncher(self, start_method=self._start_method)


def build_trainer(
    train_config: TrainConfig,
    model_config: ModelConfig,
    *,
    accelerator: str | None = None,
    **trainer_kwargs: Any,
) -> Trainer:
    """执行 `build_trainer`。
    
    参数：
    - `train_config`：传入的 `train_config` 参数。
    - `model_config`：传入的 `model_config` 参数。
    - `accelerator`：传入的 `accelerator` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    tc = train_config
    if accelerator is None:
        accelerator = tc.accelerator

    def _resolve_precision() -> str:
        if not model_config.amp:
            return "32-true"
        #
        if torch.cuda.is_available():
            if torch.cuda.is_bf16_supported():
                return "bf16-mixed"
            return "16-mixed"
        if torch.backends.mps.is_available():
            return "16-mixed"
        return "32-true"

    strategy = tc.strategy

    if strategy in ("ddp_notebook", "ddp_spawn"):
        strategy = _NotebookSpawnDDPStrategy(start_method="spawn", find_unused_parameters=True)
        _logger.info(
            "%s → spawn-based DDP to avoid OpenMP thread pool corruption after fork.",
            tc.strategy,
        )
    elif strategy == "ddp" and model_config.segmentation_head:
        strategy = _DDPStrategy(find_unused_parameters=True)
        _logger.info(
            "segmentation_head=True with strategy='ddp' → DDPStrategy(find_unused_parameters=True).",
        )
    sharded = any(s in str(strategy).lower() for s in ("fsdp", "deepspeed"))
    enable_ema = bool(tc.use_ema) and not sharded
    if tc.use_ema and sharded:
        warnings.warn(
            f"EMA disabled: RFDETREMACallback is not compatible with sharded strategies "
            f"(strategy={strategy!r}). Set use_ema=False to suppress this warning.",
            UserWarning,
            stacklevel=2,
        )

    callbacks = []

    if tc.progress_bar == "rich":
        callbacks.append(RichProgressBar(theme=RichProgressBarTheme(metrics_format=".3e")))
    elif tc.progress_bar == "tqdm":
        callbacks.append(TQDMProgressBar())

    if enable_ema:
        callbacks.append(
            RFDETREMACallback(
                decay=tc.ema_decay,
                tau=tc.ema_tau,
                update_interval_steps=tc.ema_update_interval,
            )
        )

    if tc.drop_path > 0.0:
        callbacks.append(DropPathCallback(drop_path=tc.drop_path))

    callbacks.append(
        COCOEvalCallback(
            max_dets=tc.eval_max_dets,
            segmentation=model_config.segmentation_head,
            eval_interval=tc.eval_interval,
            log_per_class_metrics=tc.log_per_class_metrics,
        )
    )

    if tc.checkpoint_interval != 1:
        callbacks.append(
            ModelCheckpoint(
                dirpath=tc.output_dir,
                filename="last",
                every_n_epochs=1,
                save_top_k=1,
                enable_version_counter=False,
                auto_insert_metric_name=False,
                verbose=False,
            )
        )

    callbacks.append(
        ModelCheckpoint(
            dirpath=tc.output_dir,
            filename="checkpoint_{epoch}",
            every_n_epochs=tc.checkpoint_interval,
            save_top_k=-1,
            enable_version_counter=False,
            auto_insert_metric_name=False,
            verbose=False,
        )
    )

    callbacks.append(
        BestModelCallback(
            output_dir=tc.output_dir,
            monitor_ema="val/ema_mAP_50_95" if enable_ema else None,
            run_test=tc.run_test,
            skip_best_epochs=tc.skip_best_epochs,
        )
    )

    if tc.early_stopping:
        callbacks.append(
            RFDETREarlyStopping(
                patience=tc.early_stopping_patience,
                min_delta=tc.early_stopping_min_delta,
                use_ema=tc.early_stopping_use_ema,
                skip_best_epochs=tc.skip_best_epochs,
            )
        )

    loggers: list = [CSVLogger(save_dir=tc.output_dir, name="", version="")]

    if tc.tensorboard:
        try:
            loggers.append(
                TensorBoardLogger(
                    save_dir=tc.output_dir,
                    name="",
                    version="",
                )
            )
        except ModuleNotFoundError as exc:
            _logger.warning("TensorBoard logging disabled: %s. Install with: pip install tensorboard", exc)

    clip_max_norm: float = tc.clip_max_norm
    sync_bn: bool = tc.sync_bn

    trainer_config: dict[str, Any] = {
        "max_epochs": tc.epochs,
        "accelerator": accelerator,
        "devices": tc.devices,
        "num_nodes": tc.num_nodes,
        "strategy": strategy,
        "precision": _resolve_precision(),
        "accumulate_grad_batches": tc.grad_accum_steps,
        "gradient_clip_val": clip_max_norm,
        "sync_batchnorm": sync_bn,
        "callbacks": callbacks,
        "logger": loggers if loggers else False,
        "enable_progress_bar": tc.progress_bar is not None,
        "default_root_dir": tc.output_dir,
        "log_every_n_steps": 50,
        "deterministic": False,
    }
    trainer_config.update(trainer_kwargs)
    return Trainer(**trainer_config)


