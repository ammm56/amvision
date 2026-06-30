"""RF-DETR core 训练处理模块：`training.callbacks.best_model`。"""

# ruff: noqa: E402

from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

import torch

from backend.service.application.models.rfdetr_core.training.lightning_bootstrap import (
    disable_lightning_model_summary_import,
)

disable_lightning_model_summary_import()

from pytorch_lightning import LightningModule, Trainer
from pytorch_lightning import __version__ as ptl_version
from pytorch_lightning.callbacks import EarlyStopping, ModelCheckpoint

from backend.service.application.models.rfdetr_core.utilities.logger import get_logger
from backend.service.application.models.rfdetr_core.utilities.package import get_version
from backend.service.application.models.rfdetr_core.utilities.state_dict import _make_fit_loop_state, strip_checkpoint

logger = get_logger()


class BestModelCallback(ModelCheckpoint):
    """RF-DETR core 类：`BestModelCallback`。"""

    FILE_EXTENSION = ".pth"

    def __init__(
        self,
        output_dir: str,
        monitor_regular: str = "val/mAP_50_95",
        monitor_ema: str | None = None,
        run_test: bool = True,
        skip_best_epochs: int = 0,
    ) -> None:
        super().__init__(
            dirpath=output_dir,
            filename="checkpoint_best_regular",
            monitor=monitor_regular,
            mode="max",
            save_top_k=1,
            save_on_train_epoch_end=False,
            verbose=False,
            auto_insert_metric_name=False,
            enable_version_counter=False,
        )
        self._monitor_ema = monitor_ema
        self._run_test = run_test
        self._best_ema: float = 0.0
        self._output_dir = Path(output_dir)
        if isinstance(skip_best_epochs, bool) or not isinstance(skip_best_epochs, int):
            raise TypeError("skip_best_epochs must be a non-negative integer")
        if skip_best_epochs < 0:
            raise ValueError("skip_best_epochs must be greater than or equal to 0")
        self._skip_best_epochs = skip_best_epochs
        self._current_pl_module: LightningModule | None = None

    @staticmethod
    def _build_checkpoint_payload(
        model_state_dict: dict[str, torch.Tensor],
        args_dict: object,
        trainer: Trainer,
        model_name: str | None = None,
    ) -> dict[str, object]:
        """执行 `_build_checkpoint_payload`。
        
        参数：
        - `model_state_dict`：传入的 `model_state_dict` 参数。
        - `args_dict`：传入的 `args_dict` 参数。
        - `trainer`：传入的 `trainer` 参数。
        - `model_name`：传入的 `model_name` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        payload: dict[str, object] = {
            "model": model_state_dict,
            "args": args_dict,
            "epoch": trainer.current_epoch,
            "state_dict": {f"model.{k}": v for k, v in model_state_dict.items()},
            "global_step": trainer.global_step,
            "pytorch-lightning_version": ptl_version,
            "loops": {"fit_loop": _make_fit_loop_state(trainer.current_epoch)},
            "optimizer_states": [],
            "lr_schedulers": [],
        }
        if model_name is not None:
            payload["model_name"] = model_name
        version = get_version()
        if version is not None:
            payload["rfdetr_version"] = version
        return payload

    @staticmethod
    def _get_ema_model_state_dict(
        trainer: Trainer,
        pl_module: LightningModule,
    ) -> dict[str, torch.Tensor]:
        """执行 `_get_ema_model_state_dict`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        for callback in trainer.callbacks:
            getter = getattr(callback, "get_ema_model_state_dict", None)
            if callable(getter):
                state_dict = getter()
                if state_dict is not None:
                    return state_dict
                break
        logger.warning(
            "EMA metric improved but EMA callback weights were unavailable; saving current model weights as fallback."
        )
        _orig = getattr(pl_module.model, "_orig_mod", None)
        raw = _orig if isinstance(_orig, torch.nn.Module) else pl_module.model
        return raw.state_dict()

    @staticmethod
    def _resolve_model_name(pl_module: LightningModule) -> str | None:
        """执行 `_resolve_model_name`。
        
        参数：
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        model_config = getattr(pl_module, "model_config", None)
        configured_name = getattr(model_config, "model_name", None) if model_config is not None else None
        if isinstance(configured_name, str):
            normalized_name = configured_name.strip()
            if normalized_name:
                return normalized_name

        config_type_name = type(model_config).__name__ if model_config is not None else ""

        if config_type_name.endswith("DeprecatedConfig"):
            raise RuntimeError(
                f"已废弃的 model config '{config_type_name}' 不再支持。"
                "请使用当前可用的 model 变体重新训练。"
            )
        if config_type_name.startswith("RFDETR") and config_type_name.endswith("Config"):
            return config_type_name.removesuffix("Config")
        return None

    def state_dict(self) -> dict[str, Any]:
        """执行 `state_dict`。
        
        返回：
        - 当前函数的执行结果。
        """
        state = super().state_dict()
        state["_best_ema"] = self._best_ema
        return state

    def load_state_dict(self, state_dict: dict[str, Any]) -> None:
        """执行 `load_state_dict`。
        
        参数：
        - `state_dict`：传入的 `state_dict` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        state = dict(state_dict)
        self._best_ema = float(state.pop("_best_ema", 0.0))
        if not math.isfinite(self._best_ema):
            self._best_ema = 0.0
        super().load_state_dict(state)

    def _save_checkpoint(self, trainer: Trainer, filepath: str) -> None:
        """执行 `_save_checkpoint`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `filepath`：传入的 `filepath` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if not trainer.is_global_zero:
            return
        pl_module = self._current_pl_module
        if pl_module is None:
            raise RuntimeError(
                f"BestModelCallback._save_checkpoint called with filepath={filepath!r} "
                f"at epoch={trainer.current_epoch} but pl_module was not set."
            )
        pth_path = Path(filepath)
        pth_path.parent.mkdir(parents=True, exist_ok=True)
        if self._monitor_ema is not None:
            model_state_dict = self._get_ema_model_state_dict(trainer, pl_module)
        else:
            _orig = getattr(pl_module.model, "_orig_mod", None)
            raw = _orig if isinstance(_orig, torch.nn.Module) else pl_module.model
            model_state_dict = raw.state_dict()
        train_config = pl_module.train_config
        dataset_class_names = getattr(trainer.datamodule, "class_names", None)
        if (
            dataset_class_names is not None
            and hasattr(train_config, "model_copy")
            and getattr(train_config, "class_names", None) is None
        ):
            train_config = train_config.model_copy(update={"class_names": dataset_class_names})
        args_dict = train_config.model_dump() if hasattr(train_config, "model_dump") else train_config
        model_name = self._resolve_model_name(pl_module)
        torch.save(
            self._build_checkpoint_payload(model_state_dict, args_dict, trainer, model_name=model_name), pth_path
        )
        self._last_global_step_saved = trainer.global_step
        logger.info("Best regular mAP saved to %s (epoch %d)", pth_path, trainer.current_epoch)

    def on_validation_end(self, trainer: Trainer, pl_module: LightningModule) -> None:
        """执行 `on_validation_end`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        self._current_pl_module = pl_module
        if trainer.current_epoch < self._skip_best_epochs:
            return
        if self.monitor not in trainer.callback_metrics:
            return
        super().on_validation_end(trainer, pl_module)

        if self._monitor_ema is None or not trainer.is_global_zero:
            return
        ema_val = trainer.callback_metrics.get(self._monitor_ema, torch.tensor(0.0)).item()
        if ema_val > self._best_ema:
            self._best_ema = ema_val
            self._output_dir.mkdir(parents=True, exist_ok=True)
            ema_state_dict = self._get_ema_model_state_dict(trainer, pl_module)
            ema_train_config = pl_module.train_config
            dataset_class_names = getattr(trainer.datamodule, "class_names", None)
            if (
                dataset_class_names is not None
                and hasattr(ema_train_config, "model_copy")
                and getattr(ema_train_config, "class_names", None) is None
            ):
                ema_train_config = ema_train_config.model_copy(update={"class_names": dataset_class_names})
            ema_args_dict = (
                ema_train_config.model_dump() if hasattr(ema_train_config, "model_dump") else ema_train_config
            )
            ema_model_name = self._resolve_model_name(pl_module)
            torch.save(
                self._build_checkpoint_payload(ema_state_dict, ema_args_dict, trainer, model_name=ema_model_name),
                self._output_dir / "checkpoint_best_ema.pth",
            )
            logger.info(
                "Best EMA mAP improved to %.4f (epoch %d)",
                ema_val,
                trainer.current_epoch,
            )

    def on_fit_end(self, trainer: Trainer, pl_module: LightningModule) -> None:
        """执行 `on_fit_end`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if not trainer.is_global_zero:
            return

        best_regular = self.best_model_score.item() if self.best_model_score is not None else 0.0
        regular_path = Path(self.best_model_path) if self.best_model_path else None
        ema_path = self._output_dir / "checkpoint_best_ema.pth"
        total_path = self._output_dir / "checkpoint_best_total.pth"

        best_is_ema = self._best_ema > best_regular
        best_path = ema_path if (best_is_ema and ema_path.exists()) else regular_path

        if best_path and best_path.exists():
            shutil.copy2(best_path, total_path)
            strip_checkpoint(total_path)
            logger.info(
                "Best total checkpoint saved from %s (regular=%.4f, ema=%.4f)",
                "EMA" if best_is_ema else "regular",
                best_regular,
                self._best_ema,
            )

        if self._run_test:
            cls_test_step = getattr(type(pl_module), "test_step", None)
            has_test_step = cls_test_step is not None and cls_test_step is not LightningModule.test_step
            if has_test_step:
                if not total_path.exists():
                    logger.warning(
                        "Skipping trainer.test() because no best checkpoint was produced. "
                        "Ensure the monitored metric is logged on evaluation epochs, that evaluation "
                        "runs often enough, and that skip_best_epochs is smaller than the number of "
                        "training epochs."
                    )
                    return
                ckpt = torch.load(total_path, map_location="cpu", weights_only=False)
                _orig = getattr(pl_module.model, "_orig_mod", None)
                raw = _orig if isinstance(_orig, torch.nn.Module) else pl_module.model
                raw.load_state_dict(ckpt["model"], strict=True)
                logger.info("Loaded best weights from %s for test evaluation.", total_path)
                trainer.test(pl_module, datamodule=trainer.datamodule, verbose=False)


class RFDETREarlyStopping(EarlyStopping):
    """RF-DETR core 类：`RFDETREarlyStopping`。"""

    _SYNTHETIC_MONITOR: str = "__rfdetr_effective_map__"

    def __init__(
        self,
        patience: int = 10,
        min_delta: float = 0.001,
        use_ema: bool = False,
        monitor_regular: str = "val/mAP_50_95",
        monitor_ema: str = "val/ema_mAP_50_95",
        verbose: bool = True,
        skip_best_epochs: int = 0,
    ) -> None:
        super().__init__(
            monitor=self._SYNTHETIC_MONITOR,
            mode="max",
            patience=patience,
            min_delta=min_delta,
            check_on_train_epoch_end=False,
            verbose=verbose,
            check_finite=True,
            strict=False,
            log_rank_zero_only=True,
        )
        if isinstance(skip_best_epochs, bool) or not isinstance(skip_best_epochs, int):
            raise TypeError("skip_best_epochs must be a non-negative integer")
        if skip_best_epochs < 0:
            raise ValueError("skip_best_epochs must be greater than or equal to 0")

        self._monitor_regular = monitor_regular
        self._monitor_ema = monitor_ema
        self._use_ema = use_ema
        self._skip_best_epochs = skip_best_epochs

    def on_validation_end(self, trainer: Trainer, pl_module: LightningModule) -> None:
        """执行 `on_validation_end`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if trainer.current_epoch < self._skip_best_epochs:
            return

        metrics = trainer.callback_metrics
        regular_tensor = metrics.get(self._monitor_regular)
        ema_tensor = metrics.get(self._monitor_ema)

        regular_val: float | None = regular_tensor.item() if regular_tensor is not None else None
        ema_val: float | None = ema_tensor.item() if ema_tensor is not None else None

        if regular_val is None and ema_val is None:
            return

        if self._use_ema and ema_val is not None:
            effective = ema_val
        elif regular_val is not None and ema_val is not None:
            effective = max(regular_val, ema_val)
        elif ema_val is not None:
            effective = ema_val
        else:
            effective = regular_val  # type: ignore[assignment]

        trainer.callback_metrics[self._SYNTHETIC_MONITOR] = torch.tensor(effective)
        super().on_validation_end(trainer, pl_module)


