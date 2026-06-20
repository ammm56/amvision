"""YOLO26 classification head。"""

from __future__ import annotations

import torch
from torch import nn

from backend.service.application.models.yolo_core_common.layers import Conv


class Classify(nn.Module):
    """YOLO26 classification head 的项目内 full core 实现。"""

    export = False

    def __init__(
        self,
        c1: int,
        c2: int,
        k: int = 1,
        s: int = 1,
        p: int | None = None,
        g: int = 1,
    ) -> None:
        """初始化 YOLO26 classification head。"""

        super().__init__()
        hidden_channels = 1280
        self.conv = Conv(c1, hidden_channels, k, s, p, g)
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.drop = nn.Dropout(p=0.0, inplace=True)
        self.linear = nn.Linear(hidden_channels, c2)

    def forward(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...] | torch.Tensor,
    ) -> torch.Tensor | tuple[torch.Tensor, torch.Tensor]:
        """把高层特征映射成分类 logits。"""

        if isinstance(x, list | tuple):
            if len(x) == 1:
                x = x[0]
            else:
                x = torch.cat(tuple(x), dim=1)
        logits = self.linear(self.drop(self.pool(self.conv(x)).flatten(1)))
        if self.training:
            return logits
        probabilities = logits.softmax(dim=1)
        if self.export:
            return probabilities
        return probabilities, logits
