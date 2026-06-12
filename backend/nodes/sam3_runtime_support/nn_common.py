"""SAM3 project-native runtime 的公共神经网络小模块。"""

from __future__ import annotations

import copy
import math

import torch
import torch.nn as nn
import torch.nn.functional as F


class LayerNorm2d(nn.Module):
    """二维特征图版本的 LayerNorm。"""

    def __init__(self, num_channels: int, eps: float = 1e-6) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.ones(num_channels))
        self.bias = nn.Parameter(torch.zeros(num_channels))
        self.eps = eps

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        mean = x.mean(dim=1, keepdim=True)
        variance = (x - mean).pow(2).mean(dim=1, keepdim=True)
        normalized = (x - mean) / torch.sqrt(variance + self.eps)
        return self.weight[:, None, None] * normalized + self.bias[:, None, None]


class MLP(nn.Module):
    """简单多层感知机。"""

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int,
        output_dim: int,
        num_layers: int,
        *,
        act: type[nn.Module] = nn.ReLU,
        sigmoid: bool = False,
        residual: bool = False,
        out_norm: nn.Module | None = None,
    ) -> None:
        super().__init__()
        self.num_layers = num_layers
        dims = [input_dim] + [hidden_dim] * (num_layers - 1) + [output_dim]
        self.layers = nn.ModuleList(nn.Linear(dims[index], dims[index + 1]) for index in range(num_layers))
        self.activation = act()
        self.use_sigmoid = bool(sigmoid)
        self.use_residual = bool(residual) and input_dim == output_dim
        self.out_norm = out_norm if out_norm is not None else nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = x
        for index, layer in enumerate(self.layers):
            x = self.activation(layer(x)) if index < self.num_layers - 1 else layer(x)
        x = self.out_norm(x)
        if self.use_residual:
            x = x + residual
        if self.use_sigmoid:
            x = x.sigmoid()
        return x


class MLPBlock(nn.Module):
    """Transformer 风格 MLP block。"""

    def __init__(
        self,
        embedding_dim: int,
        mlp_dim: int,
        activation: type[nn.Module] = nn.GELU,
    ) -> None:
        super().__init__()
        self.lin1 = nn.Linear(embedding_dim, mlp_dim)
        self.lin2 = nn.Linear(mlp_dim, embedding_dim)
        self.activation = activation()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.lin2(self.activation(self.lin1(x)))


def clone_module_list(module: nn.Module, count: int) -> nn.ModuleList:
    """复制同构子模块列表。"""

    return nn.ModuleList(copy.deepcopy(module) for _ in range(count))


class DropPath(nn.Module):
    """实现 stochastic depth。"""

    def __init__(self, drop_prob: float = 0.0, scale_by_keep: bool = True) -> None:
        super().__init__()
        self.drop_prob = float(drop_prob)
        self.scale_by_keep = bool(scale_by_keep)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.drop_prob == 0.0 or not self.training:
            return x
        keep_prob = 1.0 - self.drop_prob
        shape = (x.shape[0],) + (1,) * (x.ndim - 1)
        random_tensor = x.new_empty(shape).bernoulli_(keep_prob)
        if keep_prob > 0.0 and self.scale_by_keep:
            random_tensor.div_(keep_prob)
        return x * random_tensor


class LayerScale(nn.Module):
    """逐通道 layer scale。"""

    def __init__(self, dim: int, init_values: float = 1e-5, inplace: bool = False) -> None:
        super().__init__()
        self.gamma = nn.Parameter(init_values * torch.ones(dim))
        self.inplace = bool(inplace)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x.mul_(self.gamma) if self.inplace else x * self.gamma


def inverse_sigmoid(x: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:
    """数值稳定的 sigmoid 逆函数。"""

    x = x.clamp(min=eps, max=1.0 - eps)
    return torch.log(x / (1.0 - x))


def xywh2xyxy(x: torch.Tensor) -> torch.Tensor:
    """把 cxcywh 转成 xyxy。"""

    cx_value, cy_value, width_value, height_value = x.unbind(-1)
    half_width = width_value / 2.0
    half_height = height_value / 2.0
    return torch.stack(
        (
            cx_value - half_width,
            cy_value - half_height,
            cx_value + half_width,
            cy_value + half_height,
        ),
        dim=-1,
    )


def get_1d_sine_pe(positions: torch.Tensor, dim: int) -> torch.Tensor:
    """生成一维正弦位置编码。"""

    if dim % 2 != 0:
        raise ValueError(f"位置编码维度必须是偶数，实际得到 {dim}")
    div_term = torch.arange(0, dim, 2, dtype=positions.dtype, device=positions.device)
    div_term = torch.exp(-math.log(10000.0) * div_term / dim)
    sinusoid_input = positions[:, None] * div_term[None, :]
    return torch.stack((sinusoid_input.sin(), sinusoid_input.cos()), dim=-1).flatten(1)
