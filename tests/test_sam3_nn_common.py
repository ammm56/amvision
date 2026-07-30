"""SAM3 custom node core 公共算子测试。"""

from __future__ import annotations

import torch
from custom_nodes.sam3_segment_nodes.backend.core.nn.common import (
    LayerNorm2d,
    MLP,
    MLPBlock,
    clone_module_list,
    get_1d_sine_pe,
    inverse_sigmoid,
    xywh2xyxy,
)


def test_layer_norm_2d_preserves_shape() -> None:
    """验证 LayerNorm2d 会保留输入形状。"""

    module = LayerNorm2d(4)
    input_tensor = torch.randn(2, 4, 8, 8)
    output_tensor = module(input_tensor)

    assert tuple(output_tensor.shape) == (2, 4, 8, 8)


def test_mlp_and_mlp_block_are_callable() -> None:
    """验证 MLP 与 MLPBlock 可以处理二维张量。"""

    mlp_module = MLP(input_dim=8, hidden_dim=16, output_dim=4, num_layers=3)
    block_module = MLPBlock(embedding_dim=8, mlp_dim=16)
    input_tensor = torch.randn(3, 8)

    assert tuple(mlp_module(input_tensor).shape) == (3, 4)
    assert tuple(block_module(input_tensor).shape) == (3, 8)


def test_clone_module_list_inverse_sigmoid_and_xywh2xyxy() -> None:
    """验证公共工具函数行为稳定。"""

    clones = clone_module_list(torch.nn.Linear(4, 4), 3)
    assert len(clones) == 3

    sigmoid_input = torch.tensor([0.2, 0.5, 0.8], dtype=torch.float32)
    inverse_value = inverse_sigmoid(sigmoid_input)
    assert tuple(inverse_value.shape) == (3,)

    boxes = torch.tensor([[10.0, 20.0, 4.0, 8.0]], dtype=torch.float32)
    converted = xywh2xyxy(boxes)
    assert converted.tolist() == [[8.0, 16.0, 12.0, 24.0]]


def test_get_1d_sine_pe_shape() -> None:
    """验证一维位置编码的输出 shape。"""

    positions = torch.tensor([0.0, 1.0, 2.0], dtype=torch.float32)
    position_encoding = get_1d_sine_pe(positions, dim=8)
    assert tuple(position_encoding.shape) == (3, 8)
