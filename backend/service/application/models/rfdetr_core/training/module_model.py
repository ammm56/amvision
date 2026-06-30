"""RF-DETR core 训练处理模块：`training.module_model`。"""

# ruff: noqa: E402

from __future__ import annotations

import math
import random
import warnings
from dataclasses import replace
from typing import Any, Dict, Optional, Tuple

import torch
import torch.nn.functional as F  # noqa: N812 -- 项目约定别名，见 AGENTS.md

from backend.service.application.models.rfdetr_core.training.lightning_bootstrap import (
    disable_lightning_model_summary_import,
)

disable_lightning_model_summary_import()

from pytorch_lightning import LightningModule, seed_everything

from backend.service.application.models.rfdetr_core._namespace import _namespace_from_configs
from backend.service.application.models.rfdetr_core.config import ModelConfig, TrainConfig
from backend.service.application.models.rfdetr_core.datasets.coco import compute_multi_scale_scales
from backend.service.application.models.rfdetr_core.models.lwdetr import build_criterion_from_config, build_model_from_config
from backend.service.application.models.rfdetr_core.models._defaults import MODEL_DEFAULTS
from backend.service.application.models.rfdetr_core.models.weights import apply_lora, interpolate_position_embeddings, load_pretrain_weights
from backend.service.application.models.rfdetr_core.training.param_groups import get_param_dict
from backend.service.application.models.rfdetr_core.utilities.logger import get_logger

logger = get_logger()

_PROJECT_TRAINING_MODEL_DEFAULTS = replace(
    MODEL_DEFAULTS,
    force_no_pretrain=True,
)


class RFDETRModelModule(LightningModule):
    """RF-DETR core 类：`RFDETRModelModule`。"""

    def __init__(self, model_config: ModelConfig, train_config: TrainConfig) -> None:
        super().__init__()
        self.model_config = model_config
        self.train_config = train_config
        self.strict_loading = False

        self.model = build_model_from_config(
            model_config,
            train_config,
            defaults=_PROJECT_TRAINING_MODEL_DEFAULTS,
        )
        if model_config.pretrain_weights is not None:
            load_pretrain_weights(self.model, self.model_config)
        if model_config.backbone_lora:
            apply_lora(self.model)

        self.criterion, self.postprocess = build_criterion_from_config(
            self.model_config,
            self.train_config,
            defaults=_PROJECT_TRAINING_MODEL_DEFAULTS,
        )

        from backend.service.application.models.rfdetr_core.config import DEVICE

        accelerator = str(train_config.accelerator).lower()
        uses_cuda_accelerator = accelerator in {"auto", "gpu", "cuda"}
        compile_enabled = (
            model_config.compile and DEVICE == "cuda" and uses_cuda_accelerator and not train_config.multi_scale
        )
        if model_config.compile and train_config.multi_scale:
            logger.info("Disabling torch.compile because multi_scale=True introduces dynamic input shapes.")
        if compile_enabled:
            torch._dynamo.config.suppress_errors = True
            torch._dynamo.config.capture_scalar_outputs = True
            self.model = torch.compile(self.model, dynamic=True)

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def on_fit_start(self) -> None:
        """执行 `on_fit_start`。
        
        返回：
        - 当前函数的执行结果。
        """
        if self.train_config.seed is not None:
            seed_everything(self.train_config.seed + self.global_rank, workers=True)

    def on_train_batch_start(self, batch: Tuple, batch_idx: int) -> None:
        """执行 `on_train_batch_start`。
        
        参数：
        - `batch`：传入的 `batch` 参数。
        - `batch_idx`：传入的 `batch_idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        tc = self.train_config
        mc = self.model_config

        if tc.multi_scale and not tc.do_random_resize_via_padding:
            samples, _ = batch
            scales = compute_multi_scale_scales(mc.resolution, tc.expanded_scales, mc.patch_size, mc.num_windows)
            step = self.trainer.global_step
            random.seed(step)
            scale = random.choice(scales)
            with torch.no_grad():
                samples.tensors = F.interpolate(samples.tensors, size=scale, mode="bilinear", align_corners=False)
                samples.mask = (
                    F.interpolate(samples.mask.unsqueeze(1).float(), size=scale, mode="nearest").squeeze(1).bool()
                )

    def training_step(self, batch: Tuple, batch_idx: int) -> torch.Tensor:
        """执行 `training_step`。
        
        参数：
        - `batch`：传入的 `batch` 参数。
        - `batch_idx`：传入的 `batch_idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        samples, targets = batch
        batch_size = len(targets)
        outputs = self.model(samples, targets)
        loss_dict = self.criterion(outputs, targets)
        weight_dict = self.criterion.weight_dict
        loss = sum(loss_dict[k] * weight_dict[k] for k in loss_dict if k in weight_dict)
        loss_scaled = loss / self.trainer.accumulate_grad_batches
        train_log_sync_dist = bool(self.train_config.train_log_sync_dist)
        train_log_on_step = bool(self.train_config.train_log_on_step)
        self.log_dict(
            {f"train/{k}": v for k, v in loss_dict.items()},
            on_step=train_log_on_step,
            on_epoch=True,
            sync_dist=train_log_sync_dist,
            batch_size=batch_size,
        )
        self.log(
            "train/loss",
            loss,
            prog_bar=True,
            on_step=train_log_on_step,
            on_epoch=True,
            sync_dist=train_log_sync_dist,
            batch_size=batch_size,
        )
        optimizer = self.optimizers()
        if isinstance(optimizer, list):
            optimizer = optimizer[0]
        group_lrs = [pg["lr"] for pg in optimizer.param_groups if "lr" in pg]
        if group_lrs:
            base_lr = group_lrs[0]
            min_lr = min(group_lrs)
            max_lr = max(group_lrs)
            self.log("train/lr", base_lr, prog_bar=True, on_step=True, on_epoch=False)
            self.log("train/lr_min", min_lr, prog_bar=True, on_step=True, on_epoch=False)
            self.log("train/lr_max", max_lr, prog_bar=True, on_step=True, on_epoch=False)
        return loss_scaled

    def validation_step(self, batch: Tuple, batch_idx: int) -> Dict[str, Any]:
        """执行 `validation_step`。
        
        参数：
        - `batch`：传入的 `batch` 参数。
        - `batch_idx`：传入的 `batch_idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        samples, targets = batch
        outputs = self.model(samples)
        if self.train_config.compute_val_loss:
            loss_dict = self.criterion(outputs, targets)
            weight_dict = self.criterion.weight_dict
            loss = sum(loss_dict[k] * weight_dict[k] for k in loss_dict if k in weight_dict)
            self.log("val/loss", loss, prog_bar=True, on_epoch=True, sync_dist=True, batch_size=len(targets))

        orig_sizes = torch.stack([t["orig_size"] for t in targets])
        results = self.postprocess(outputs, orig_sizes)
        return {"results": results, "targets": targets}

    @property
    def _use_fused_optimizer(self) -> bool:
        """执行 `_use_fused_optimizer`。
        
        返回：
        - 当前函数的执行结果。
        """
        return (
            self.model_config.fused_optimizer
            and torch.cuda.is_available()
            and torch.cuda.is_bf16_supported()
            and str(self.trainer.precision) in {"bf16-mixed", "bf16", "bf16-true"}
        )

    def configure_optimizers(self) -> Dict[str, Any]:
        """执行 `configure_optimizers`。
        
        返回：
        - 当前函数的执行结果。
        """
        tc = self.train_config
        ns = _namespace_from_configs(self.model_config, tc)

        model_for_params = getattr(self.model, "_orig_mod", self.model)
        param_dicts = get_param_dict(ns, model_for_params)
        param_dicts = [p for p in param_dicts if p["params"].requires_grad]
        optimizer = torch.optim.AdamW(
            param_dicts,
            lr=tc.lr,
            weight_decay=tc.weight_decay,
            fused=self._use_fused_optimizer,
        )

        total_steps = int(self.trainer.estimated_stepping_batches)
        steps_per_epoch = max(1, total_steps // tc.epochs)
        warmup_steps = int(steps_per_epoch * tc.warmup_epochs)

        def lr_lambda(current_step: int) -> float:
            if current_step < warmup_steps:
                return float(current_step) / float(max(1, warmup_steps))
            if tc.lr_scheduler == "cosine":
                progress = float(current_step - warmup_steps) / float(max(1, total_steps - warmup_steps))
                return tc.lr_min_factor + (1 - tc.lr_min_factor) * 0.5 * (1 + math.cos(math.pi * progress))
            if current_step < tc.lr_drop * steps_per_epoch:
                return 1.0
            return 0.1

        scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda=lr_lambda)

        return {
            "optimizer": optimizer,
            "lr_scheduler": {"scheduler": scheduler, "interval": "step"},
        }

    def clip_gradients(
        self,
        optimizer: torch.optim.Optimizer,
        gradient_clip_val: Optional[float] = None,
        gradient_clip_algorithm: Optional[str] = None,
    ) -> None:
        """执行 `clip_gradients`。
        
        参数：
        - `optimizer`：传入的 `optimizer` 参数。
        - `gradient_clip_val`：传入的 `gradient_clip_val` 参数。
        - `gradient_clip_algorithm`：传入的 `gradient_clip_algorithm` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if self._use_fused_optimizer:
            if gradient_clip_val and gradient_clip_val > 0:
                torch.nn.utils.clip_grad_norm_(self.parameters(), gradient_clip_val)
        else:
            super().clip_gradients(
                optimizer,
                gradient_clip_val=gradient_clip_val,
                gradient_clip_algorithm=gradient_clip_algorithm,
            )

    def test_step(self, batch: Tuple, batch_idx: int) -> Dict[str, Any]:
        """执行 `test_step`。
        
        参数：
        - `batch`：传入的 `batch` 参数。
        - `batch_idx`：传入的 `batch_idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        samples, targets = batch
        outputs = self.model(samples)
        if self.train_config.compute_test_loss:
            loss_dict = self.criterion(outputs, targets)
            weight_dict = self.criterion.weight_dict
            loss = sum(loss_dict[k] * weight_dict[k] for k in loss_dict if k in weight_dict)
            self.log("test/loss", loss, sync_dist=True, batch_size=len(targets))

        orig_sizes = torch.stack([t["orig_size"] for t in targets])
        results = self.postprocess(outputs, orig_sizes)
        return {"results": results, "targets": targets}

    def predict_step(self, batch: Tuple, batch_idx: int, dataloader_idx: int = 0) -> Any:
        """执行 `predict_step`。
        
        参数：
        - `batch`：传入的 `batch` 参数。
        - `batch_idx`：传入的 `batch_idx` 参数。
        - `dataloader_idx`：传入的 `dataloader_idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        samples, targets = batch
        with torch.no_grad():
            outputs = self.model(samples)
        orig_sizes = torch.stack([t["orig_size"] for t in targets])
        return self.postprocess(outputs, orig_sizes)

    def on_load_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        """执行 `on_load_checkpoint`。
        
        参数：
        - `checkpoint`：传入的 `checkpoint` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if "model" in checkpoint and "state_dict" not in checkpoint:
            checkpoint["state_dict"] = {"model." + k: v for k, v in checkpoint["model"].items()}

        if "state_dict" in checkpoint:
            interpolate_position_embeddings(
                checkpoint["state_dict"],
                self.model_config.positional_encoding_size,
            )

        if "legacy_ema_state_dict" in checkpoint:
            self._pending_legacy_ema_state = checkpoint["legacy_ema_state_dict"]
            warnings.warn(
                "Checkpoint contains legacy EMA weights (`legacy_ema_state_dict`). "
                "Add RFDETREMACallback to your trainer callbacks to restore them; "
                "without it the stashed weights will be ignored.",
                UserWarning,
                stacklevel=2,
            )

    def reinitialize_detection_head(self, num_classes: int) -> None:
        """执行 `reinitialize_detection_head`。
        
        参数：
        - `num_classes`：传入的 `num_classes` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        self.model.reinitialize_detection_head(num_classes)


