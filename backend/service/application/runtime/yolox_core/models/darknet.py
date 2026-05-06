"""项目内 YOLOX backbone 实现。"""

from __future__ import annotations

import torch
from torch import nn

from .network_blocks import BaseConv, CSPLayer, DWConv, Focus, ResLayer, SPPBottleneck


class Darknet(nn.Module):
    """实现原 YOLOX 中 YOLOv3 分支使用的 Darknet 主干。"""

    depth2blocks = {21: [1, 2, 2, 1], 53: [2, 8, 8, 4]}

    def __init__(
        self,
        depth: int,
        in_channels: int = 3,
        stem_out_channels: int = 32,
        out_features: tuple[str, str, str] = ("dark3", "dark4", "dark5"),
    ) -> None:
        """初始化 Darknet 主干。

        参数：
        - depth：Darknet 深度，支持 21 或 53。
        - in_channels：输入图像通道数。
        - stem_out_channels：stem 阶段输出通道数。
        - out_features：需要返回的特征层名称。
        """

        super().__init__()
        if not out_features:
            raise ValueError("请提供 Darknet 的输出特征层名称")
        if depth not in self.depth2blocks:
            raise ValueError(f"不支持的 Darknet 深度: {depth}")

        self.out_features = out_features
        self.stem = nn.Sequential(
            BaseConv(in_channels, stem_out_channels, ksize=3, stride=1, act="lrelu"),
            *self.make_group_layer(stem_out_channels, num_blocks=1, stride=2),
        )
        current_channels = stem_out_channels * 2
        num_blocks = self.depth2blocks[depth]

        self.dark2 = nn.Sequential(
            *self.make_group_layer(current_channels, num_blocks[0], stride=2)
        )
        current_channels *= 2
        self.dark3 = nn.Sequential(
            *self.make_group_layer(current_channels, num_blocks[1], stride=2)
        )
        current_channels *= 2
        self.dark4 = nn.Sequential(
            *self.make_group_layer(current_channels, num_blocks[2], stride=2)
        )
        current_channels *= 2
        self.dark5 = nn.Sequential(
            *self.make_group_layer(current_channels, num_blocks[3], stride=2),
            *self.make_spp_block([current_channels, current_channels * 2], current_channels * 2),
        )

    def make_group_layer(self, in_channels: int, num_blocks: int, stride: int = 1) -> list[nn.Module]:
        """构造一组 Darknet 卷积与残差块。"""

        return [
            BaseConv(in_channels, in_channels * 2, ksize=3, stride=stride, act="lrelu"),
            *[ResLayer(in_channels * 2) for _ in range(num_blocks)],
        ]

    def make_spp_block(self, filters_list: list[int], in_filters: int) -> list[nn.Module]:
        """构造 YOLOv3 SPP 尾部块。"""

        return [
            BaseConv(in_filters, filters_list[0], 1, stride=1, act="lrelu"),
            BaseConv(filters_list[0], filters_list[1], 3, stride=1, act="lrelu"),
            SPPBottleneck(
                in_channels=filters_list[1],
                out_channels=filters_list[0],
                activation="lrelu",
            ),
            BaseConv(filters_list[0], filters_list[1], 3, stride=1, act="lrelu"),
            BaseConv(filters_list[1], filters_list[0], 1, stride=1, act="lrelu"),
        ]

    def forward(self, x: torch.Tensor):
        """执行 Darknet 前向，并返回指定层特征。"""

        outputs: dict[str, torch.Tensor] = {}
        x = self.stem(x)
        outputs["stem"] = x
        x = self.dark2(x)
        outputs["dark2"] = x
        x = self.dark3(x)
        outputs["dark3"] = x
        x = self.dark4(x)
        outputs["dark4"] = x
        x = self.dark5(x)
        outputs["dark5"] = x
        return {name: feature for name, feature in outputs.items() if name in self.out_features}


class CSPDarknet(nn.Module):
    """实现与原 YOLOX 兼容的 CSPDarknet backbone。"""

    def __init__(
        self,
        dep_mul: float,
        wid_mul: float,
        out_features: tuple[str, str, str] = ("dark3", "dark4", "dark5"),
        depthwise: bool = False,
        act: str = "silu",
    ) -> None:
        """初始化 CSPDarknet。

        参数：
        - dep_mul：深度缩放因子。
        - wid_mul：宽度缩放因子。
        - out_features：需要输出的特征层名。
        - depthwise：是否使用 depthwise 卷积。
        - act：激活函数名称。
        """

        super().__init__()
        if not out_features:
            raise ValueError("请提供 Darknet 的输出特征层名称")

        self.out_features = out_features
        conv_type = DWConv if depthwise else BaseConv
        base_channels = int(wid_mul * 64)
        base_depth = max(round(dep_mul * 3), 1)

        self.stem = Focus(3, base_channels, ksize=3, act=act)
        self.dark2 = nn.Sequential(
            conv_type(base_channels, base_channels * 2, 3, 2, act=act),
            CSPLayer(
                base_channels * 2,
                base_channels * 2,
                n=base_depth,
                depthwise=depthwise,
                act=act,
            ),
        )
        self.dark3 = nn.Sequential(
            conv_type(base_channels * 2, base_channels * 4, 3, 2, act=act),
            CSPLayer(
                base_channels * 4,
                base_channels * 4,
                n=base_depth * 3,
                depthwise=depthwise,
                act=act,
            ),
        )
        self.dark4 = nn.Sequential(
            conv_type(base_channels * 4, base_channels * 8, 3, 2, act=act),
            CSPLayer(
                base_channels * 8,
                base_channels * 8,
                n=base_depth * 3,
                depthwise=depthwise,
                act=act,
            ),
        )
        self.dark5 = nn.Sequential(
            conv_type(base_channels * 8, base_channels * 16, 3, 2, act=act),
            SPPBottleneck(base_channels * 16, base_channels * 16, activation=act),
            CSPLayer(
                base_channels * 16,
                base_channels * 16,
                n=base_depth,
                shortcut=False,
                depthwise=depthwise,
                act=act,
            ),
        )

    def forward(self, x):
        """执行 backbone 前向，并返回指定特征层。"""

        outputs: dict[str, object] = {}
        x = self.stem(x)
        outputs["stem"] = x
        x = self.dark2(x)
        outputs["dark2"] = x
        x = self.dark3(x)
        outputs["dark3"] = x
        x = self.dark4(x)
        outputs["dark4"] = x
        x = self.dark5(x)
        outputs["dark5"] = x
        return {name: feature for name, feature in outputs.items() if name in self.out_features}