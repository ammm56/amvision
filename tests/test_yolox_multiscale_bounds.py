"""小尺寸、多尺度和单张批次的真实前向边界回归。"""

import pytest
import torch

from backend.service.application.models.yolox_core.models.build import build_yolox_detection_model
from backend.service.application.models.yolox_core.training.batch_probe import yolox_probe_input_size
from backend.service.application.models.yolox_core.training.trainer import random_resize_yolox_input_size


@pytest.mark.parametrize("base,span", [((160, 160), 5), ((64, 32), 5), ((320, 32), 1), ((32, 64), 1), ((640, 960), 5)])
def test_sampled_sizes_are_valid_and_bounded_by_probe(base, span):
    """不能生成零宽或 32 像素边，AutoBatch 最大尺寸覆盖同一采样范围。"""
    maximum = yolox_probe_input_size(base, span)
    for seed in range(100):
        size = random_resize_yolox_input_size(base_input_size=base, multiscale_range=span, random_seed=seed)
        assert all(64 <= value <= limit and value % 32 == 0 for value, limit in zip(size, maximum))
        assert size == random_resize_yolox_input_size(base_input_size=base, multiscale_range=span, random_seed=seed)


def test_disabled_and_standard_multiscale_are_unchanged():
    """不改变固定尺寸，也不改变标准 640 多尺度的采样序列。"""
    import random

    assert random_resize_yolox_input_size(base_input_size=(160, 160), multiscale_range=0, random_seed=0) == (160, 160)
    for seed in range(100):
        expected = random.Random(seed).randint(15, 25) * 32
        assert random_resize_yolox_input_size(base_input_size=(640, 640), multiscale_range=5, random_seed=seed) == (expected, expected)


def test_minimum_multiscale_supports_batch_one_backward():
    """真实 nano 模型在最小采样尺寸下完成带标签 loss 和反向传播。"""
    model = build_yolox_detection_model(torch_module=torch, model_scale="nano", num_classes=2).train()
    image = torch.zeros(1, 3, 64, 64)
    targets = torch.tensor([[[0, 32, 32, 16, 16]]], dtype=torch.float32)
    loss = model(image, targets)["total_loss"]
    assert torch.isfinite(loss)
    loss.backward()
    assert any(parameter.grad is not None for parameter in model.parameters())
