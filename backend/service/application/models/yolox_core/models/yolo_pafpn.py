"""项目内 YOLOX PAFPN neck 实现。"""

from __future__ import annotations

import torch
import torch.nn as nn

from .darknet import CSPDarknet
from .network_blocks import BaseConv, CSPLayer, DWConv


class YOLOPAFPN(nn.Module):
    """实现与原 YOLOX 兼容的 YOLOPAFPN 结构。"""

    def __init__(
        self,
        depth: float = 1.0,
        width: float = 1.0,
        in_features: tuple[str, str, str] = ("dark3", "dark4", "dark5"),
        in_channels: list[int] | tuple[int, int, int] = (256, 512, 1024),
        depthwise: bool = False,
        act: str = "silu",
    ) -> None:
        """初始化 YOLOPAFPN。"""

        super().__init__()
        self.backbone = CSPDarknet(depth, width, depthwise=depthwise, act=act)
        self.in_features = in_features
        self.in_channels = list(in_channels)
        conv_type = DWConv if depthwise else BaseConv

        self.upsample = nn.Upsample(scale_factor=2, mode="nearest")
        self.lateral_conv0 = BaseConv(
            int(self.in_channels[2] * width),
            int(self.in_channels[1] * width),
            1,
            1,
            act=act,
        )
        self.C3_p4 = CSPLayer(
            int(2 * self.in_channels[1] * width),
            int(self.in_channels[1] * width),
            round(3 * depth),
            False,
            depthwise=depthwise,
            act=act,
        )
        self.reduce_conv1 = BaseConv(
            int(self.in_channels[1] * width),
            int(self.in_channels[0] * width),
            1,
            1,
            act=act,
        )
        self.C3_p3 = CSPLayer(
            int(2 * self.in_channels[0] * width),
            int(self.in_channels[0] * width),
            round(3 * depth),
            False,
            depthwise=depthwise,
            act=act,
        )
        self.bu_conv2 = conv_type(
            int(self.in_channels[0] * width),
            int(self.in_channels[0] * width),
            3,
            2,
            act=act,
        )
        self.C3_n3 = CSPLayer(
            int(2 * self.in_channels[0] * width),
            int(self.in_channels[1] * width),
            round(3 * depth),
            False,
            depthwise=depthwise,
            act=act,
        )
        self.bu_conv1 = conv_type(
            int(self.in_channels[1] * width),
            int(self.in_channels[1] * width),
            3,
            2,
            act=act,
        )
        self.C3_n4 = CSPLayer(
            int(2 * self.in_channels[1] * width),
            int(self.in_channels[2] * width),
            round(3 * depth),
            False,
            depthwise=depthwise,
            act=act,
        )

    def forward(self, inputs: torch.Tensor):
        """执行 PAFPN 前向，输出三个尺度的 PAN 特征。"""

        out_features = self.backbone(inputs)
        x2, x1, x0 = [out_features[name] for name in self.in_features]

        fpn_out0 = self.lateral_conv0(x0)
        f_out0 = self.upsample(fpn_out0)
        f_out0 = torch.cat([f_out0, x1], 1)
        f_out0 = self.C3_p4(f_out0)

        fpn_out1 = self.reduce_conv1(f_out0)
        f_out1 = self.upsample(fpn_out1)
        f_out1 = torch.cat([f_out1, x2], 1)
        pan_out2 = self.C3_p3(f_out1)

        p_out1 = self.bu_conv2(pan_out2)
        p_out1 = torch.cat([p_out1, fpn_out1], 1)
        pan_out1 = self.C3_n3(p_out1)

        p_out0 = self.bu_conv1(pan_out1)
        p_out0 = torch.cat([p_out0, fpn_out0], 1)
        pan_out0 = self.C3_n4(p_out0)
        return pan_out2, pan_out1, pan_out0