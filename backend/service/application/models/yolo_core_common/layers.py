"""YOLO 主线共用基础层。"""

from __future__ import annotations

import math

import torch
from torch import nn


def autopad(kernel_size: int, padding: int | None = None, dilation: int = 1) -> int:
    """按 same 输出规则推导卷积 padding。"""

    if dilation > 1:
        kernel_size = dilation * (kernel_size - 1) + 1
    if padding is None:
        return kernel_size // 2
    return padding


def make_divisible(value: float, divisor: int) -> int:
    """把通道数上调到指定除数的整数倍。"""

    return int(math.ceil(value / divisor) * divisor)


class Conv(nn.Module):
    """标准卷积块。"""

    default_act = nn.SiLU()

    def __init__(
        self,
        c1: int,
        c2: int,
        k: int = 1,
        s: int = 1,
        p: int | None = None,
        g: int = 1,
        d: int = 1,
        act: bool | nn.Module = True,
    ) -> None:
        """初始化卷积、BN 和激活层。"""

        super().__init__()
        self.conv = nn.Conv2d(
            c1,
            c2,
            k,
            s,
            autopad(k, p, d),
            groups=g,
            dilation=d,
            bias=False,
        )
        self.bn = nn.BatchNorm2d(c2)
        if act is True:
            self.act = self.default_act
        elif isinstance(act, nn.Module):
            self.act = act
        else:
            self.act = nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行卷积前向。"""

        return self.act(self.bn(self.conv(x)))


class DWConv(Conv):
    """Depthwise 卷积块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        k: int = 1,
        s: int = 1,
        d: int = 1,
        act: bool | nn.Module = True,
    ) -> None:
        """初始化 depthwise 卷积。"""

        super().__init__(c1, c2, k, s, g=math.gcd(c1, c2), d=d, act=act)


class DistributionFocalLossDecoder(nn.Module):
    """把回归分布解码为边界框距离。"""

    def __init__(self, reg_max: int = 16) -> None:
        """初始化 DFL 解码器。"""

        super().__init__()
        self.reg_max = reg_max
        self.register_buffer(
            "projection",
            torch.arange(reg_max, dtype=torch.float32).view(1, 1, reg_max, 1),
            persistent=False,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 DFL 解码。"""

        batch_size, _, anchor_count = x.shape
        prediction = x.view(batch_size, 4, self.reg_max, anchor_count).softmax(dim=2)
        projection = self.projection.to(device=prediction.device, dtype=prediction.dtype)
        return (prediction * projection).sum(dim=2)
