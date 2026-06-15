"""项目内 YOLOX 网络基础模块。"""

from __future__ import annotations

import torch
import torch.nn as nn


def get_activation(name: str = "silu", inplace: bool = True) -> nn.Module:
    """按名称构造激活函数。"""

    if name == "silu":
        return nn.SiLU(inplace=inplace)
    if name == "relu":
        return nn.ReLU(inplace=inplace)
    if name == "lrelu":
        return nn.LeakyReLU(0.1, inplace=inplace)
    raise AttributeError(f"Unsupported act type: {name}")


class BaseConv(nn.Module):
    """由 Conv2d、BatchNorm2d 和激活函数组成的基础卷积块。"""

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        ksize: int,
        stride: int,
        groups: int = 1,
        bias: bool = False,
        act: str = "silu",
    ) -> None:
        """初始化基础卷积块。"""

        super().__init__()
        padding = (ksize - 1) // 2
        self.conv = nn.Conv2d(
            in_channels,
            out_channels,
            kernel_size=ksize,
            stride=stride,
            padding=padding,
            groups=groups,
            bias=bias,
        )
        self.bn = nn.BatchNorm2d(out_channels)
        self.act = get_activation(act, inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行标准前向计算。"""

        return self.act(self.bn(self.conv(x)))

    def fuseforward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 fuse 后的近似前向计算。"""

        return self.act(self.conv(x))


class DWConv(nn.Module):
    """实现 YOLOX 中使用的 depthwise separable convolution。"""

    def __init__(self, in_channels: int, out_channels: int, ksize: int, stride: int = 1, act: str = "silu") -> None:
        """初始化深度可分离卷积块。"""

        super().__init__()
        self.dconv = BaseConv(
            in_channels,
            in_channels,
            ksize=ksize,
            stride=stride,
            groups=in_channels,
            act=act,
        )
        self.pconv = BaseConv(in_channels, out_channels, ksize=1, stride=1, groups=1, act=act)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行深度卷积后再做逐点卷积。"""

        return self.pconv(self.dconv(x))


class Bottleneck(nn.Module):
    """实现 YOLOX backbone 与 neck 中使用的 bottleneck 单元。"""

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        shortcut: bool = True,
        expansion: float = 0.5,
        depthwise: bool = False,
        act: str = "silu",
    ) -> None:
        """初始化 bottleneck 单元。"""

        super().__init__()
        hidden_channels = int(out_channels * expansion)
        conv_type = DWConv if depthwise else BaseConv
        self.conv1 = BaseConv(in_channels, hidden_channels, 1, stride=1, act=act)
        self.conv2 = conv_type(hidden_channels, out_channels, 3, stride=1, act=act)
        self.use_add = shortcut and in_channels == out_channels

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 bottleneck 前向计算。"""

        y = self.conv2(self.conv1(x))
        if self.use_add:
            y = y + x
        return y


class ResLayer(nn.Module):
    """实现 YOLOv3 Darknet 主干中使用的残差层。"""

    def __init__(self, in_channels: int) -> None:
        """初始化残差层。

        参数：
        - in_channels：输入与输出通道数。
        """

        super().__init__()
        mid_channels = in_channels // 2
        self.layer1 = BaseConv(
            in_channels,
            mid_channels,
            ksize=1,
            stride=1,
            act="lrelu",
        )
        self.layer2 = BaseConv(
            mid_channels,
            in_channels,
            ksize=3,
            stride=1,
            act="lrelu",
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行残差前向计算。"""

        return x + self.layer2(self.layer1(x))


class SPPBottleneck(nn.Module):
    """实现 YOLOX dark5 阶段使用的 SPP bottleneck。"""

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_sizes: tuple[int, int, int] = (5, 9, 13),
        activation: str = "silu",
    ) -> None:
        """初始化 SPP bottleneck。"""

        super().__init__()
        hidden_channels = in_channels // 2
        self.conv1 = BaseConv(in_channels, hidden_channels, 1, stride=1, act=activation)
        self.max_pools = nn.ModuleList(
            [nn.MaxPool2d(kernel_size=kernel_size, stride=1, padding=kernel_size // 2) for kernel_size in kernel_sizes]
        )
        self.conv2 = BaseConv(
            hidden_channels * (len(kernel_sizes) + 1),
            out_channels,
            1,
            stride=1,
            act=activation,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 SPP 聚合。"""

        x = self.conv1(x)
        x = torch.cat([x] + [pool(x) for pool in self.max_pools], dim=1)
        return self.conv2(x)


class CSPLayer(nn.Module):
    """实现 YOLOX 中的 C3 / CSP 层。"""

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        n: int = 1,
        shortcut: bool = True,
        expansion: float = 0.5,
        depthwise: bool = False,
        act: str = "silu",
    ) -> None:
        """初始化 CSP 层。"""

        super().__init__()
        hidden_channels = int(out_channels * expansion)
        self.conv1 = BaseConv(in_channels, hidden_channels, 1, stride=1, act=act)
        self.conv2 = BaseConv(in_channels, hidden_channels, 1, stride=1, act=act)
        self.conv3 = BaseConv(2 * hidden_channels, out_channels, 1, stride=1, act=act)
        self.m = nn.Sequential(
            *[
                Bottleneck(
                    hidden_channels,
                    hidden_channels,
                    shortcut=shortcut,
                    expansion=1.0,
                    depthwise=depthwise,
                    act=act,
                )
                for _ in range(n)
            ]
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 CSP 分支聚合。"""

        x1 = self.m(self.conv1(x))
        x2 = self.conv2(x)
        return self.conv3(torch.cat((x1, x2), dim=1))


class Focus(nn.Module):
    """实现 YOLOX stem 中的 Focus 折叠操作。"""

    def __init__(self, in_channels: int, out_channels: int, ksize: int = 1, stride: int = 1, act: str = "silu") -> None:
        """初始化 Focus 模块。"""

        super().__init__()
        self.conv = BaseConv(in_channels * 4, out_channels, ksize, stride, act=act)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """把空间信息折叠到通道维并执行卷积。"""

        patch_top_left = x[..., ::2, ::2]
        patch_top_right = x[..., ::2, 1::2]
        patch_bottom_left = x[..., 1::2, ::2]
        patch_bottom_right = x[..., 1::2, 1::2]
        x = torch.cat(
            (patch_top_left, patch_bottom_left, patch_top_right, patch_bottom_right),
            dim=1,
        )
        return self.conv(x)