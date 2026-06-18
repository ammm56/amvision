"""YOLOv8 backbone 和 neck 使用的基础模块。"""

from __future__ import annotations

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common import Conv


class Concat(nn.Module):
    """按指定维度拼接多个输入张量。"""

    def __init__(self, dimension: int = 1) -> None:
        """初始化拼接模块。"""

        super().__init__()
        self.dimension = dimension

    def forward(self, x: list[torch.Tensor] | tuple[torch.Tensor, ...]) -> torch.Tensor:
        """执行拼接。"""

        if not isinstance(x, list | tuple) or len(x) < 2:
            raise InvalidRequestError("Concat 至少需要两个输入张量")
        return torch.cat(tuple(x), dim=self.dimension)


class Bottleneck(nn.Module):
    """YOLOv8 bottleneck 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        shortcut: bool = True,
        g: int = 1,
        k: tuple[int, int] = (3, 3),
        e: float = 0.5,
    ) -> None:
        """初始化 bottleneck。"""

        super().__init__()
        hidden_channels = int(c2 * e)
        self.cv1 = Conv(c1, hidden_channels, k[0], 1)
        self.cv2 = Conv(hidden_channels, c2, k[1], 1, g=g)
        self.add = shortcut and c1 == c2

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 bottleneck 前向。"""

        y = self.cv2(self.cv1(x))
        if self.add:
            return x + y
        return y


class C2f(nn.Module):
    """YOLOv8 C2f 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        n: int = 1,
        shortcut: bool = False,
        g: int = 1,
        e: float = 0.5,
    ) -> None:
        """初始化 C2f 模块。"""

        super().__init__()
        self.hidden_channels = int(c2 * e)
        self.cv1 = Conv(c1, 2 * self.hidden_channels, 1, 1)
        self.cv2 = Conv((2 + n) * self.hidden_channels, c2, 1, 1)
        self.m = nn.ModuleList(
            Bottleneck(
                self.hidden_channels,
                self.hidden_channels,
                shortcut=shortcut,
                g=g,
                e=1.0,
            )
            for _ in range(n)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 C2f 前向。"""

        y = list(self.cv1(x).chunk(2, dim=1))
        y.extend(module(y[-1]) for module in self.m)
        return self.cv2(torch.cat(y, dim=1))


class SPPF(nn.Module):
    """YOLOv8 SPPF 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        k: int = 5,
        n: int = 3,
        shortcut: bool = False,
    ) -> None:
        """初始化 SPPF 模块。"""

        super().__init__()
        hidden_channels = c1 // 2
        self.cv1 = Conv(c1, hidden_channels, 1, 1, act=False)
        self.cv2 = Conv(hidden_channels * (n + 1), c2, 1, 1)
        self.pool = nn.MaxPool2d(kernel_size=k, stride=1, padding=k // 2)
        self.pool_count = n
        self.add = shortcut and c1 == c2

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 SPPF 前向。"""

        y = [self.cv1(x)]
        y.extend(self.pool(y[-1]) for _ in range(self.pool_count))
        output = self.cv2(torch.cat(y, dim=1))
        if self.add:
            return output + x
        return output
