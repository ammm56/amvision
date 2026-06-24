"""YOLOE project-native 基础 nn 模块。"""

from __future__ import annotations

import contextvars
import math

import numpy as np
import torch
from torch import nn
import torch.nn.functional as F

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError


_YOLOE_CONV_USE_BATCH_NORM: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "yoloe_conv_use_batch_norm",
    default=True,
)


class YoloeConcat(nn.Module):
    """按通道维拼接多路特征。"""

    def __init__(self, dimension: int = 1) -> None:
        super().__init__()
        self.dimension = int(dimension)

    def forward(self, x: list[torch.Tensor] | tuple[torch.Tensor, ...]) -> torch.Tensor:
        if not isinstance(x, list | tuple) or len(x) < 2:
            raise InvalidRequestError("YOLOE Concat 至少需要两个输入张量")
        return torch.cat(tuple(x), dim=self.dimension)


def _autopad(kernel_size: int, padding: int | None = None, dilation: int = 1) -> int:
    """按 same 输出规则推导卷积 padding。"""

    if dilation > 1:
        kernel_size = dilation * (kernel_size - 1) + 1
    if padding is None:
        return kernel_size // 2
    return int(padding)


def _make_divisible(value: float, divisor: int) -> int:
    """把通道数上调到指定除数的整数倍。"""

    return int(np.ceil(value / divisor) * divisor)


class YoloeConv(nn.Module):
    """YOLOE project-native 标准卷积块。"""

    default_act = nn.SiLU(inplace=True)

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
        super().__init__()
        self.use_batch_norm = bool(_YOLOE_CONV_USE_BATCH_NORM.get())
        self.conv = nn.Conv2d(
            c1,
            c2,
            k,
            s,
            _autopad(k, p, d),
            groups=g,
            dilation=d,
            bias=not self.use_batch_norm,
        )
        self.bn = nn.BatchNorm2d(c2, eps=1e-3, momentum=0.03) if self.use_batch_norm else nn.Identity()
        self.act = self.default_act if act is True else act if isinstance(act, nn.Module) else nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.act(self.bn(self.conv(x)))


class YoloeDWConv(YoloeConv):
    """YOLOE depth-wise convolution。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        k: int = 1,
        s: int = 1,
        d: int = 1,
        act: bool | nn.Module = True,
    ) -> None:
        super().__init__(c1, c2, k, s, g=math.gcd(c1, c2), d=d, act=act)


class YoloeBottleneck(nn.Module):
    """YOLOE bottleneck 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        shortcut: bool = True,
        g: int = 1,
        k: tuple[int, int] = (3, 3),
        e: float = 0.5,
    ) -> None:
        super().__init__()
        hidden_channels = int(c2 * e)
        self.cv1 = YoloeConv(c1, hidden_channels, k[0], 1)
        self.cv2 = YoloeConv(hidden_channels, c2, k[1], 1, g=g)
        self.add = shortcut and c1 == c2

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.cv2(self.cv1(x))
        return x + y if self.add else y


class YoloeC2f(nn.Module):
    """YOLOE v8 主线使用的 C2f 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        n: int = 1,
        shortcut: bool = False,
        g: int = 1,
        e: float = 0.5,
    ) -> None:
        super().__init__()
        self.hidden_channels = int(c2 * e)
        self.cv1 = YoloeConv(c1, 2 * self.hidden_channels, 1, 1)
        self.cv2 = YoloeConv((2 + n) * self.hidden_channels, c2, 1, 1)
        self.m = nn.ModuleList(
            YoloeBottleneck(
                self.hidden_channels,
                self.hidden_channels,
                shortcut=shortcut,
                g=g,
                e=1.0,
            )
            for _ in range(n)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = list(self.cv1(x).chunk(2, dim=1))
        y.extend(module(y[-1]) for module in self.m)
        return self.cv2(torch.cat(y, dim=1))


class YoloeC3(nn.Module):
    """YOLOE C3 CSP 模块，用于 C3k/C3k2 分支的权重对齐。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        n: int = 1,
        shortcut: bool = True,
        g: int = 1,
        e: float = 0.5,
    ) -> None:
        super().__init__()
        hidden_channels = int(c2 * e)
        self.cv1 = YoloeConv(c1, hidden_channels, 1, 1)
        self.cv2 = YoloeConv(c1, hidden_channels, 1, 1)
        self.cv3 = YoloeConv(2 * hidden_channels, c2, 1)
        self.m = nn.Sequential(
            *(
                YoloeBottleneck(
                    hidden_channels,
                    hidden_channels,
                    shortcut=shortcut,
                    g=g,
                    e=1.0,
                )
                for _ in range(n)
            )
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.cv3(torch.cat((self.m(self.cv1(x)), self.cv2(x)), dim=1))


class YoloeC3k(YoloeC3):
    """YOLOE C3k 模块，保持 upstream C3k 的 state_dict 命名。"""

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
        super().__init__(c1, c2, n, shortcut, g, e)
        hidden_channels = int(c2 * e)
        self.m = nn.Sequential(
            *(
                YoloeBottleneck(
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


class YoloeC3k2(YoloeC2f):
    """YOLOE 11/26 使用的 C3k2 模块。"""

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
        super().__init__(c1, c2, n, shortcut, g, e)
        self.m = nn.ModuleList(
            nn.Sequential(
                YoloeBottleneck(
                    self.hidden_channels,
                    self.hidden_channels,
                    shortcut=shortcut,
                    g=g,
                ),
                YoloePSABlock(
                    self.hidden_channels,
                    attn_ratio=0.5,
                    num_heads=max(self.hidden_channels // 64, 1),
                ),
            )
            if attn
            else YoloeC3k(
                self.hidden_channels,
                self.hidden_channels,
                2,
                shortcut=shortcut,
                g=g,
            )
            if c3k
            else YoloeBottleneck(
                self.hidden_channels,
                self.hidden_channels,
                shortcut=shortcut,
                g=g,
            )
            for _ in range(n)
        )


class YoloeAttention(nn.Module):
    """YOLOE 多头 attention 模块。"""

    def __init__(self, dim: int, num_heads: int = 8, attn_ratio: float = 0.5) -> None:
        super().__init__()
        self.num_heads = max(1, int(num_heads))
        self.head_dim = dim // self.num_heads
        self.key_dim = max(1, int(self.head_dim * attn_ratio))
        self.scale = float(self.key_dim) ** -0.5
        qk_channels = self.key_dim * self.num_heads
        hidden_channels = dim + qk_channels * 2
        self.qkv = YoloeConv(dim, hidden_channels, 1, act=False)
        self.proj = YoloeConv(dim, dim, 1, act=False)
        self.pe = YoloeConv(dim, dim, 3, 1, g=dim, act=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
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
        attended = (v @ attention.transpose(-2, -1)).view(batch_size, channels, height, width)
        position_encoded = self.pe(v.reshape(batch_size, channels, height, width))
        return self.proj(attended + position_encoded)


class YoloePSABlock(nn.Module):
    """YOLOE PSA block。"""

    def __init__(
        self,
        c: int,
        attn_ratio: float = 0.5,
        num_heads: int = 4,
        shortcut: bool = True,
    ) -> None:
        super().__init__()
        self.attn = YoloeAttention(c, attn_ratio=attn_ratio, num_heads=num_heads)
        self.ffn = nn.Sequential(
            YoloeConv(c, c * 2, 1),
            YoloeConv(c * 2, c, 1, act=False),
        )
        self.add = bool(shortcut)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        attn_output = self.attn(x)
        x = x + attn_output if self.add else attn_output
        ffn_output = self.ffn(x)
        return x + ffn_output if self.add else ffn_output


class YoloeC2PSA(nn.Module):
    """YOLOE 11 使用的 C2PSA 模块。"""

    def __init__(self, c1: int, c2: int, n: int = 1, e: float = 0.5) -> None:
        super().__init__()
        if c1 != c2:
            raise ServiceConfigurationError(
                "YOLOE C2PSA 要求输入输出通道一致",
                details={"input_channels": c1, "output_channels": c2},
            )
        self.c = int(c1 * e)
        self.cv1 = YoloeConv(c1, 2 * self.c, 1, 1)
        self.cv2 = YoloeConv(2 * self.c, c1, 1, 1)
        self.m = nn.Sequential(
            *(
                YoloePSABlock(
                    self.c,
                    attn_ratio=0.5,
                    num_heads=max(self.c // 64, 1),
                )
                for _ in range(n)
            )
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        a, b = self.cv1(x).split((self.c, self.c), dim=1)
        return self.cv2(torch.cat((a, self.m(b)), dim=1))


class YoloeSPPF(nn.Module):
    """YOLOE SPPF 模块。"""

    def __init__(self, c1: int, c2: int, k: int = 5, n: int = 3, shortcut: bool = False) -> None:
        super().__init__()
        hidden_channels = c1 // 2
        self.cv1 = YoloeConv(c1, hidden_channels, 1, 1, act=False)
        self.cv2 = YoloeConv(hidden_channels * (n + 1), c2, 1, 1)
        self.pool = nn.MaxPool2d(kernel_size=k, stride=1, padding=k // 2)
        self.pool_count = int(n)
        self.add = bool(shortcut) and c1 == c2

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = [self.cv1(x)]
        y.extend(self.pool(y[-1]) for _ in range(self.pool_count))
        output = self.cv2(torch.cat(y, dim=1))
        return output + x if self.add else output


class YoloeDistributionFocalLossDecoder(nn.Module):
    """把回归分布解码为边界框距离。"""

    def __init__(self, c1: int = 16) -> None:
        super().__init__()
        self.conv = nn.Conv2d(c1, 1, 1, bias=False).requires_grad_(False)
        projection = torch.arange(c1, dtype=torch.float32)
        self.conv.weight.data[:] = nn.Parameter(projection.view(1, c1, 1, 1))
        self.c1 = int(c1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch_size, _channels, anchors = x.shape
        return self.conv(x.view(batch_size, 4, self.c1, anchors).transpose(2, 1).softmax(1)).view(batch_size, 4, anchors)


class YoloeProto(nn.Module):
    """YOLOE segmentation proto 头。"""

    def __init__(self, c1: int, c_: int = 256, c2: int = 32) -> None:
        super().__init__()
        self.cv1 = YoloeConv(c1, c_, k=3)
        self.upsample = nn.ConvTranspose2d(c_, c_, 2, 2, 0, bias=True)
        self.cv2 = YoloeConv(c_, c_, k=3)
        self.cv3 = YoloeConv(c_, c2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.cv3(self.cv2(self.upsample(self.cv1(x))))


class YoloeProto26(YoloeProto):
    """YOLOE 26 segmentation proto 头，融合多层特征生成 mask proto。"""

    def __init__(self, ch: tuple[int, ...], c_: int = 256, c2: int = 32, nc: int = 80) -> None:
        super().__init__(c_, c_, c2)
        self.feat_refine = nn.ModuleList(YoloeConv(input_channels, ch[0], k=1) for input_channels in ch[1:])
        self.feat_fuse = YoloeConv(ch[0], c_, k=3)
        self.semseg = nn.Sequential(
            YoloeConv(ch[0], c_, k=3),
            YoloeConv(c_, c_, k=3),
            nn.Conv2d(c_, int(nc), 1),
        )

    def forward(self, x: list[torch.Tensor] | tuple[torch.Tensor, ...], return_semseg: bool = False) -> torch.Tensor:
        if not isinstance(x, list | tuple) or not x:
            raise InvalidRequestError("YOLOE 26 proto 要求输入多层特征")
        feature = x[0]
        for index, refine_layer in enumerate(self.feat_refine):
            refined = refine_layer(x[index + 1])
            refined = F.interpolate(refined, size=feature.shape[2:], mode="nearest")
            feature = feature + refined
        proto = super().forward(self.feat_fuse(feature))
        if self.training and return_semseg:
            return proto, self.semseg(feature)  # type: ignore[return-value]
        return proto


class YoloeSpatialAwareVisualPromptEmbedding(nn.Module):
    """YOLOE SAVPE 模块。当前仅为权重兼容与后续 visual-prompt 复用保留。"""

    def __init__(self, ch: tuple[int, ...], c3: int, embed: int) -> None:
        super().__init__()
        self.cv1 = nn.ModuleList(
            nn.Sequential(
                YoloeConv(input_channels, c3, 3),
                YoloeConv(c3, c3, 3),
                nn.Upsample(scale_factor=index * 2) if index in {1, 2} else nn.Identity(),
            )
            for index, input_channels in enumerate(ch)
        )
        self.cv2 = nn.ModuleList(
            nn.Sequential(
                YoloeConv(input_channels, c3, 1),
                nn.Upsample(scale_factor=index * 2) if index in {1, 2} else nn.Identity(),
            )
            for index, input_channels in enumerate(ch)
        )
        self.c = 16
        self.cv3 = nn.Conv2d(3 * c3, embed, 1)
        self.cv4 = nn.Conv2d(3 * c3, self.c, 3, padding=1)
        self.cv5 = nn.Conv2d(1, self.c, 3, padding=1)
        self.cv6 = nn.Sequential(YoloeConv(2 * self.c, self.c, 3), nn.Conv2d(self.c, self.c, 3, padding=1))

    def forward(self, x: list[torch.Tensor], vp: torch.Tensor) -> torch.Tensor:
        y = [self.cv2[index](feature) for index, feature in enumerate(x)]
        y = self.cv4(torch.cat(y, dim=1))

        refined = [self.cv1[index](feature) for index, feature in enumerate(x)]
        refined = self.cv3(torch.cat(refined, dim=1))

        batch_size, channels, height, width = refined.shape
        prompt_count = int(vp.shape[1])
        refined = refined.view(batch_size, channels, -1)

        y = y.reshape(batch_size, 1, self.c, height, width).expand(-1, prompt_count, -1, -1, -1).reshape(
            batch_size * prompt_count,
            self.c,
            height,
            width,
        )
        vp = vp.reshape(batch_size, prompt_count, 1, height, width).reshape(batch_size * prompt_count, 1, height, width)
        y = self.cv6(torch.cat((y, self.cv5(vp)), dim=1))

        y = y.reshape(batch_size, prompt_count, self.c, -1)
        vp = vp.reshape(batch_size, prompt_count, 1, -1)
        score = y * vp + torch.logical_not(vp) * torch.finfo(y.dtype).min
        score = F.softmax(score, dim=-1).to(y.dtype)
        aggregated = score.transpose(-2, -3) @ refined.reshape(batch_size, self.c, channels // self.c, -1).transpose(-1, -2)
        return F.normalize(aggregated.transpose(-2, -3).reshape(batch_size, prompt_count, -1), dim=-1, p=2)


class YoloeBatchNormContrastiveHead(nn.Module):
    """YOLOE 文本/图像对比头。"""

    def __init__(self, embed_dims: int) -> None:
        super().__init__()
        self.norm = nn.BatchNorm2d(embed_dims, eps=1e-3, momentum=0.03)
        self.bias = nn.Parameter(torch.tensor([-10.0]))
        self.logit_scale = nn.Parameter(-1.0 * torch.ones([]))

    def fuse(self) -> None:
        del self.norm
        del self.bias
        del self.logit_scale
        self.forward = self.forward_fuse  # type: ignore[assignment]

    @staticmethod
    def forward_fuse(x: torch.Tensor, w: torch.Tensor) -> torch.Tensor:
        return x

    def forward(self, x: torch.Tensor, w: torch.Tensor) -> torch.Tensor:
        normalized_features = self.norm(x)
        normalized_text = F.normalize(w, dim=-1, p=2)
        scores = torch.einsum("bchw,bkc->bkhw", normalized_features, normalized_text)
        return scores * self.logit_scale.exp() + self.bias


class YoloeSwiGluFeedForward(nn.Module):
    """YOLOE reprta 使用的 SwiGLU FFN。"""

    def __init__(self, guide_channels: int, embed_channels: int, expansion: int = 4) -> None:
        super().__init__()
        self.w12 = nn.Linear(guide_channels, expansion * embed_channels)
        self.w3 = nn.Linear(expansion * embed_channels // 2, embed_channels)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x12 = self.w12(x)
        x1, x2 = x12.chunk(2, dim=-1)
        hidden = F.silu(x1) * x2
        return self.w3(hidden)


class YoloeResidualTextAdapter(nn.Module):
    """YOLOE reprta 残差适配器。"""

    def __init__(self, module: nn.Module) -> None:
        super().__init__()
        self.m = module
        nn.init.zeros_(self.m.w3.bias)
        nn.init.zeros_(self.m.w3.weight)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.m(x)


__all__ = [
    "_YOLOE_CONV_USE_BATCH_NORM",
    "_make_divisible",
    "YoloeBatchNormContrastiveHead",
    "YoloeBottleneck",
    "YoloeC2PSA",
    "YoloeC2f",
    "YoloeC3",
    "YoloeC3k",
    "YoloeC3k2",
    "YoloeConcat",
    "YoloeConv",
    "YoloeDWConv",
    "YoloeDistributionFocalLossDecoder",
    "YoloeProto",
    "YoloeProto26",
    "YoloeResidualTextAdapter",
    "YoloeSPPF",
    "YoloeSpatialAwareVisualPromptEmbedding",
    "YoloeSwiGluFeedForward",
]
