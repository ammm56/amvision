"""RF-DETR full core tiny loss backward 验收。"""

from __future__ import annotations

from pathlib import Path
import warnings

import pytest
import torch

from backend.service.application.models.rfdetr_core.config import (
    PretrainWeightsCompatibilityWarning,
    SegmentationTrainConfig,
    TrainConfig,
)
from backend.service.application.models.rfdetr_core.factory import (
    build_rfdetr_full_core_config,
)
from backend.service.application.models.rfdetr_core.training.module_model import (
    RFDETRModelModule,
)
from backend.service.application.models.rfdetr_core.utilities.tensors import NestedTensor
from backend.service.domain.models.model_task_types import (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


@pytest.mark.parametrize(
    ("task_type", "image_size", "train_config_type", "expects_mask_loss"),
    (
        (DETECTION_TASK_TYPE, 64, TrainConfig, False),
        (SEGMENTATION_TASK_TYPE, 72, SegmentationTrainConfig, True),
    ),
)
def test_rfdetr_tiny_loss_backward(
    tmp_path: Path,
    task_type: str,
    image_size: int,
    train_config_type: type[TrainConfig],
    expects_mask_loss: bool,
) -> None:
    """验证 RF-DETR tiny batch 可以完成 criterion loss backward。"""

    model_config = build_rfdetr_full_core_config(
        task_type=task_type,
        model_scale="nano",
        num_classes=3,
        device="cpu",
    )
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=PretrainWeightsCompatibilityWarning,
        )
        model_config.num_queries = 8
        model_config.num_select = 8
        model_config.group_detr = 1

    train_config = train_config_type(
        dataset_dir=str(tmp_path / "dataset"),
        output_dir=str(tmp_path / "output"),
        batch_size=1,
        grad_accum_steps=1,
        multi_scale=False,
        use_ema=False,
        tensorboard=False,
        num_workers=0,
        accelerator="cpu",
        devices=1,
        compute_val_loss=False,
        compute_test_loss=False,
    )
    module = RFDETRModelModule(model_config, train_config)
    module.train()

    samples, targets = _build_tiny_batch(
        image_size=image_size,
        include_masks=expects_mask_loss,
    )
    outputs = module.model(samples, targets)
    loss_dict = module.criterion(outputs, targets)
    loss = sum(
        loss_dict[name] * module.criterion.weight_dict[name]
        for name in loss_dict
        if name in module.criterion.weight_dict
    )

    assert torch.isfinite(loss)
    if expects_mask_loss:
        assert "loss_mask_ce" in loss_dict
        assert "loss_mask_dice" in loss_dict
    else:
        assert "loss_mask_ce" not in loss_dict
        assert "loss_mask_dice" not in loss_dict

    loss.backward()

    grad_abs_sum = _sum_gradient_abs(module.model)
    assert grad_abs_sum > 0.0


def _build_tiny_batch(
    *,
    image_size: int,
    include_masks: bool,
) -> tuple[NestedTensor, list[dict[str, torch.Tensor]]]:
    """构造一个最小 RF-DETR 训练 batch。"""

    image = torch.randn(1, 3, image_size, image_size)
    mask = torch.zeros((1, image_size, image_size), dtype=torch.bool)
    samples = NestedTensor(image, mask)
    target: dict[str, torch.Tensor] = {
        "labels": torch.tensor([1], dtype=torch.long),
        "boxes": torch.tensor([[0.5, 0.5, 0.25, 0.25]], dtype=torch.float32),
        "orig_size": torch.tensor([image_size, image_size], dtype=torch.long),
        "size": torch.tensor([image_size, image_size], dtype=torch.long),
        "image_id": torch.tensor([0], dtype=torch.long),
    }
    if include_masks:
        target_mask = torch.zeros((1, image_size, image_size), dtype=torch.float32)
        start = image_size // 4
        end = image_size - start
        target_mask[:, start:end, start:end] = 1.0
        target["masks"] = target_mask
    return samples, [target]


def _sum_gradient_abs(model: torch.nn.Module) -> float:
    """统计模型参数梯度绝对值总和。"""

    total = 0.0
    for parameter in model.parameters():
        if parameter.grad is None:
            continue
        total += float(parameter.grad.detach().abs().sum().item())
    return total
