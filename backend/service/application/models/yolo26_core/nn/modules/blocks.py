"""YOLO26 backbone 和 neck 使用的结构模块。"""

from __future__ import annotations

import torch
from torch import nn

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.models.yolo_core_common.layers import Conv


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
    """YOLO26 bottleneck 模块。"""

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

        output = self.cv2(self.cv1(x))
        if self.add:
            return x + output
        return output


class C2f(nn.Module):
    """YOLO26 C2f 基础结构，用于承接 C3k2 的 CSP 分支。"""

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

        chunks = list(self.cv1(x).chunk(2, dim=1))
        chunks.extend(module(chunks[-1]) for module in self.m)
        return self.cv2(torch.cat(chunks, dim=1))


class C3(nn.Module):
    """YOLO26 C3 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        n: int = 1,
        shortcut: bool = True,
        g: int = 1,
        e: float = 0.5,
    ) -> None:
        """初始化 C3 模块。"""

        super().__init__()
        hidden_channels = int(c2 * e)
        self.cv1 = Conv(c1, hidden_channels, 1, 1)
        self.cv2 = Conv(c1, hidden_channels, 1, 1)
        self.cv3 = Conv(2 * hidden_channels, c2, 1, 1)
        self.m = nn.Sequential(
            *(
                Bottleneck(
                    hidden_channels,
                    hidden_channels,
                    shortcut=shortcut,
                    g=g,
                    k=(1, 3),
                    e=1.0,
                )
                for _ in range(n)
            )
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 C3 前向。"""

        return self.cv3(torch.cat((self.m(self.cv1(x)), self.cv2(x)), dim=1))


class C3k(C3):
    """支持可调 kernel size 的 C3 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        n: int = 1,
        shortcut: bool = True,
        g: int = 1,
        e: float = 0.5,
        k: int = 3,
    ) -> None:
        """初始化 C3k 模块。"""

        super().__init__(c1, c2, n=n, shortcut=shortcut, g=g, e=e)
        hidden_channels = int(c2 * e)
        self.m = nn.Sequential(
            *(
                Bottleneck(
                    hidden_channels,
                    hidden_channels,
                    shortcut=shortcut,
                    g=g,
                    k=(k, k),
                    e=1.0,
                )
                for _ in range(n)
            )
        )


class Attention(nn.Module):
    """YOLO26 PSA 使用的多头注意力。"""

    def __init__(self, dim: int, num_heads: int = 8, attn_ratio: float = 0.5) -> None:
        """初始化注意力模块。"""

        super().__init__()
        self.num_heads = max(1, int(num_heads))
        self.head_dim = dim // self.num_heads
        self.key_dim = max(1, int(self.head_dim * attn_ratio))
        self.scale = float(self.key_dim) ** -0.5
        qk_channels = self.key_dim * self.num_heads
        hidden_channels = dim + qk_channels * 2
        self.qkv = Conv(dim, hidden_channels, 1, act=False)
        self.proj = Conv(dim, dim, 1, act=False)
        self.pe = Conv(dim, dim, 3, 1, g=dim, act=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行注意力前向。"""

        batch_size, channels, height, width = x.shape
        token_count = height * width
        qkv = self.qkv(x)
        q, k, v = qkv.view(
            batch_size,
            self.num_heads,
            (self.key_dim * 2) + self.head_dim,
            token_count,
        ).split([self.key_dim, self.key_dim, self.head_dim], dim=2)
        attention = (q.transpose(-2, -1) @ k) * self.scale
        attention = attention.softmax(dim=-1)
        attended = (v @ attention.transpose(-2, -1)).view(
            batch_size, channels, height, width
        )
        return self.proj(
            attended + self.pe(v.reshape(batch_size, channels, height, width))
        )


class PSABlock(nn.Module):
    """YOLO26 PSA block。"""

    def __init__(
        self,
        c: int,
        attn_ratio: float = 0.5,
        num_heads: int = 4,
        shortcut: bool = True,
    ) -> None:
        """初始化 PSA block。"""

        super().__init__()
        self.attn = Attention(c, attn_ratio=attn_ratio, num_heads=num_heads)
        self.ffn = nn.Sequential(Conv(c, c * 2, 1), Conv(c * 2, c, 1, act=False))
        self.add = shortcut

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 PSA block 前向。"""

        attention_output = self.attn(x)
        x = x + attention_output if self.add else attention_output
        ffn_output = self.ffn(x)
        return x + ffn_output if self.add else ffn_output


class C2PSA(nn.Module):
    """YOLO26 使用的 C2PSA 模块。"""

    def __init__(self, c1: int, c2: int, n: int = 1, e: float = 0.5) -> None:
        """初始化 C2PSA 模块。"""

        super().__init__()
        if c1 != c2:
            raise ServiceConfigurationError(
                "YOLO26 C2PSA 要求输入输出通道一致",
                details={"input_channels": c1, "output_channels": c2},
            )
        self.hidden_channels = int(c1 * e)
        self.cv1 = Conv(c1, 2 * self.hidden_channels, 1, 1)
        self.cv2 = Conv(2 * self.hidden_channels, c1, 1, 1)
        self.m = nn.Sequential(
            *(
                PSABlock(
                    self.hidden_channels,
                    attn_ratio=0.5,
                    num_heads=max(self.hidden_channels // 64, 1),
                )
                for _ in range(n)
            )
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 C2PSA 前向。"""

        a, b = self.cv1(x).split((self.hidden_channels, self.hidden_channels), dim=1)
        return self.cv2(torch.cat((a, self.m(b)), dim=1))


class C3k2(C2f):
    """YOLO26 C3k2 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        n: int = 1,
        c3k: bool = False,
        e: float = 0.5,
        attn: bool = False,
        g: int = 1,
        shortcut: bool = True,
    ) -> None:
        """初始化 C3k2 模块。"""

        super().__init__(c1, c2, n=n, shortcut=shortcut, g=g, e=e)
        self.m = nn.ModuleList(
            nn.Sequential(
                Bottleneck(
                    self.hidden_channels, self.hidden_channels, shortcut=shortcut, g=g
                ),
                PSABlock(
                    self.hidden_channels,
                    attn_ratio=0.5,
                    num_heads=max(self.hidden_channels // 64, 1),
                ),
            )
            if attn
            else C3k(
                self.hidden_channels, self.hidden_channels, 2, shortcut=shortcut, g=g
            )
            if c3k
            else Bottleneck(
                self.hidden_channels, self.hidden_channels, shortcut=shortcut, g=g
            )
            for _ in range(n)
        )


class SPPF(nn.Module):
    """YOLO26 SPPF 模块。"""

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

        outputs = [self.cv1(x)]
        outputs.extend(self.pool(outputs[-1]) for _ in range(self.pool_count))
        output = self.cv2(torch.cat(outputs, dim=1))
        return output + x if self.add else output
