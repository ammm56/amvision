"""SAM3 单图 interactive 所需的视觉骨干模块。"""

from __future__ import annotations

import math
from typing import Callable

import torch
from torch import nn
import torch.nn.functional as F
import torch.utils.checkpoint as checkpoint

from .common import DropPath, LayerScale


def compute_axial_cis(dim: int, end_x: int, end_y: int, theta: float = 10000.0, scale_pos: float = 1.0) -> torch.Tensor:
    """生成二维 rotary embedding 频率。"""

    freqs_x = 1.0 / (theta ** (torch.arange(0, dim, 4)[: (dim // 4)].float() / dim))
    freqs_y = 1.0 / (theta ** (torch.arange(0, dim, 4)[: (dim // 4)].float() / dim))

    t = torch.arange(end_x * end_y, dtype=torch.float32)
    t_x = (t % end_x).float() * scale_pos
    t_y = torch.div(t, end_x, rounding_mode="floor").float() * scale_pos

    freqs_x = torch.outer(t_x, freqs_x)
    freqs_y = torch.outer(t_y, freqs_y)
    freqs_cis_x = torch.polar(torch.ones_like(freqs_x), freqs_x)
    freqs_cis_y = torch.polar(torch.ones_like(freqs_y), freqs_y)
    return torch.cat([freqs_cis_x, freqs_cis_y], dim=-1)


def reshape_for_broadcast(freqs_cis: torch.Tensor, x: torch.Tensor) -> torch.Tensor:
    """把 rope 频率 reshape 到可广播形状。"""

    ndim = x.ndim
    if ndim < 2:
        raise ValueError("reshape_for_broadcast 要求输入至少二维")
    if freqs_cis.shape != (x.shape[-2], x.shape[-1]):
        raise ValueError("rope 频率尺寸与输入张量不匹配")
    shape = [dimension if index >= ndim - 2 else 1 for index, dimension in enumerate(x.shape)]
    return freqs_cis.view(*shape)


def apply_rotary_enc(
    xq: torch.Tensor,
    xk: torch.Tensor,
    freqs_cis: torch.Tensor,
    repeat_freqs_k: bool = False,
) -> tuple[torch.Tensor, torch.Tensor]:
    """对 query/key 应用 rotary encoding。"""

    xq_complex = torch.view_as_complex(xq.float().reshape(*xq.shape[:-1], -1, 2))
    xk_complex = torch.view_as_complex(xk.float().reshape(*xk.shape[:-1], -1, 2)) if xk.shape[-2] != 0 else None
    freqs_cis = reshape_for_broadcast(freqs_cis, xq_complex)
    xq_out = torch.view_as_real(xq_complex * freqs_cis).flatten(3)
    if xk_complex is None:
        return xq_out.type_as(xq).to(xq.device), xk
    if repeat_freqs_k and (repeat_count := xk_complex.shape[-2] // xq_complex.shape[-2]) > 1:
        freqs_cis = freqs_cis.repeat(*([1] * (freqs_cis.ndim - 2)), repeat_count, 1)
    xk_out = torch.view_as_real(xk_complex * freqs_cis).flatten(3)
    return xq_out.type_as(xq).to(xq.device), xk_out.type_as(xk).to(xk.device)


def window_partition(x: torch.Tensor, window_size: int) -> tuple[torch.Tensor, tuple[int, int]]:
    """把特征图分成窗口。"""

    batch_size, height, width, channels = x.shape
    pad_h = (window_size - height % window_size) % window_size
    pad_w = (window_size - width % window_size) % window_size
    if pad_h > 0 or pad_w > 0:
        x = F.pad(x, (0, 0, 0, pad_w, 0, pad_h))
    padded_height, padded_width = height + pad_h, width + pad_w
    x = x.view(
        batch_size,
        padded_height // window_size,
        window_size,
        padded_width // window_size,
        window_size,
        channels,
    )
    windows = x.permute(0, 1, 3, 2, 4, 5).contiguous().view(-1, window_size, window_size, channels)
    return windows, (padded_height, padded_width)


def window_unpartition(
    windows: torch.Tensor,
    window_size: int,
    padded_hw: tuple[int, int],
    hw: tuple[int, int],
) -> torch.Tensor:
    """把窗口还原成原始特征图。"""

    padded_height, padded_width = padded_hw
    height, width = hw
    batch_size = windows.shape[0] // (padded_height * padded_width // window_size // window_size)
    x = windows.view(
        batch_size,
        padded_height // window_size,
        padded_width // window_size,
        window_size,
        window_size,
        -1,
    )
    x = x.permute(0, 1, 3, 2, 4, 5).contiguous().view(batch_size, padded_height, padded_width, -1)
    if padded_height > height or padded_width > width:
        x = x[:, :height, :width, :].contiguous()
    return x


def get_abs_pos(
    abs_pos: torch.Tensor,
    has_cls_token: bool,
    hw: tuple[int, int],
    retain_cls_token: bool = False,
    tiling: bool = False,
) -> torch.Tensor:
    """按目标尺寸重采样绝对位置编码。"""

    if retain_cls_token and not has_cls_token:
        raise ValueError("retain_cls_token=True 时要求 has_cls_token=True")

    height, width = hw
    if has_cls_token:
        cls_pos = abs_pos[:, :1]
        abs_pos = abs_pos[:, 1:]

    xy_num = abs_pos.shape[1]
    size = int(math.sqrt(xy_num))
    if size * size != xy_num:
        raise ValueError("绝对位置编码长度不是完全平方数")

    if size != height or size != width:
        new_abs_pos = abs_pos.reshape(1, size, size, -1).permute(0, 3, 1, 2)
        if tiling:
            new_abs_pos = new_abs_pos.tile([1, 1] + [target // source + 1 for target, source in zip((height, width), new_abs_pos.shape[2:])])[
                :,
                :,
                :height,
                :width,
            ]
        else:
            new_abs_pos = F.interpolate(new_abs_pos, size=(height, width), mode="bicubic", align_corners=False)
        if not retain_cls_token:
            return new_abs_pos.permute(0, 2, 3, 1)
        return torch.cat([cls_pos, new_abs_pos.permute(0, 2, 3, 1).reshape(1, height * width, -1)], dim=1)

    if not retain_cls_token:
        return abs_pos.reshape(1, height, width, -1)
    return torch.cat([cls_pos, abs_pos], dim=1)


class PositionEmbeddingSine(nn.Module):
    """二维正弦位置编码。"""

    def __init__(
        self,
        num_pos_feats: int,
        temperature: int = 10000,
        normalize: bool = True,
        scale: float | None = None,
    ) -> None:
        super().__init__()
        if num_pos_feats % 2 != 0:
            raise ValueError("PositionEmbeddingSine 需要偶数维 num_pos_feats")
        self.num_pos_feats = num_pos_feats // 2
        self.temperature = temperature
        self.normalize = bool(normalize)
        if scale is not None and not normalize:
            raise ValueError("normalize=False 时不能指定 scale")
        self.scale = 2 * math.pi if scale is None else scale
        self.cache: dict[tuple[int, int], torch.Tensor] = {}

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        cache_key = (x.shape[-2], x.shape[-1])
        cached = self.cache.get(cache_key)
        if cached is not None and cached.device == x.device:
            return cached[None].repeat(x.shape[0], 1, 1, 1)

        y_embed = (
            torch.arange(1, x.shape[-2] + 1, dtype=torch.float32, device=x.device)
            .view(1, -1, 1)
            .repeat(x.shape[0], 1, x.shape[-1])
        )
        x_embed = (
            torch.arange(1, x.shape[-1] + 1, dtype=torch.float32, device=x.device)
            .view(1, 1, -1)
            .repeat(x.shape[0], x.shape[-2], 1)
        )
        if self.normalize:
            eps = 1e-6
            y_embed = y_embed / (y_embed[:, -1:, :] + eps) * self.scale
            x_embed = x_embed / (x_embed[:, :, -1:] + eps) * self.scale

        dim_t = torch.arange(self.num_pos_feats, dtype=torch.float32, device=x.device)
        dim_t = self.temperature ** (2 * (dim_t // 2) / self.num_pos_feats)
        pos_x = x_embed[:, :, :, None] / dim_t
        pos_y = y_embed[:, :, :, None] / dim_t
        pos_x = torch.stack((pos_x[:, :, :, 0::2].sin(), pos_x[:, :, :, 1::2].cos()), dim=4).flatten(3)
        pos_y = torch.stack((pos_y[:, :, :, 0::2].sin(), pos_y[:, :, :, 1::2].cos()), dim=4).flatten(3)
        pos = torch.cat((pos_y, pos_x), dim=3).permute(0, 3, 1, 2)
        self.cache[cache_key] = pos[0]
        return pos


class PatchEmbed(nn.Module):
    """图像 patch embedding。"""

    def __init__(
        self,
        kernel_size: tuple[int, int] = (16, 16),
        stride: tuple[int, int] = (16, 16),
        padding: tuple[int, int] = (0, 0),
        in_chans: int = 3,
        embed_dim: int = 768,
        bias: bool = True,
    ) -> None:
        super().__init__()
        self.proj = nn.Conv2d(in_chans, embed_dim, kernel_size=kernel_size, stride=stride, padding=padding, bias=bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.proj(x).permute(0, 2, 3, 1)


class VisionMlp(nn.Module):
    """ViT block 内部使用的前馈层。"""

    def __init__(self, in_features: int, hidden_features: int, act_layer: type[nn.Module] = nn.GELU, drop: float = 0.0) -> None:
        super().__init__()
        self.fc1 = nn.Linear(in_features, hidden_features)
        self.act = act_layer()
        self.drop1 = nn.Dropout(drop)
        self.fc2 = nn.Linear(hidden_features, in_features)
        self.drop2 = nn.Dropout(drop)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.drop1(self.act(self.fc1(x)))
        x = self.drop2(self.fc2(x))
        return x


class VisionAttention(nn.Module):
    """ViT backbone 使用的 attention。"""

    def __init__(
        self,
        dim: int,
        num_heads: int = 8,
        qkv_bias: bool = True,
        input_size: tuple[int, int] | None = None,
        cls_token: bool = False,
        use_rope: bool = False,
        rope_theta: float = 10000.0,
        rope_pt_size: tuple[int, int] | None = None,
        rope_interp: bool = False,
    ) -> None:
        super().__init__()
        self.num_heads = num_heads
        self.head_dim = dim // num_heads
        self.scale = self.head_dim**-0.5
        self.cls_token = bool(cls_token)
        self.qkv = nn.Linear(dim, dim * 3, bias=qkv_bias)
        self.proj = nn.Linear(dim, dim)

        self.use_rope = bool(use_rope)
        self.input_size = input_size
        self.rope_theta = rope_theta
        self.rope_pt_size = rope_pt_size
        self.rope_interp = rope_interp
        self.freqs_cis: torch.Tensor | None = None
        if self.use_rope:
            self._setup_rope_freqs(input_size)

    def _setup_rope_freqs(self, input_size: tuple[int, int] | None = None) -> None:
        if not self.use_rope:
            self.freqs_cis = None
            return
        if input_size is None:
            raise ValueError("启用 rope 时必须提供 input_size")
        rope_pt_size = self.rope_pt_size or input_size
        scale_pos = 1.0
        if self.rope_interp:
            scale_pos = rope_pt_size[0] / input_size[0]
        freqs_cis = compute_axial_cis(
            dim=self.head_dim,
            end_x=input_size[0],
            end_y=input_size[1],
            theta=self.rope_theta,
            scale_pos=scale_pos,
        )
        if self.cls_token:
            t = torch.zeros(self.head_dim // 2, dtype=torch.float32, device=freqs_cis.device)
            cls_freqs_cis = torch.polar(torch.ones_like(t), t)[None, :]
            freqs_cis = torch.cat([cls_freqs_cis, freqs_cis], dim=0)
        self.freqs_cis = freqs_cis

    def _apply_rope(self, q: torch.Tensor, k: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        if not self.use_rope:
            return q, k
        if self.freqs_cis is None:
            raise RuntimeError("rope 频率尚未初始化")
        return apply_rotary_enc(q, k, freqs_cis=self.freqs_cis.to(q.device))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        cls_token_count = 1 if self.cls_token else 0
        if x.ndim == 4:
            batch_size, height, width, _channels = x.shape
            if cls_token_count != 0:
                raise ValueError("四维特征图模式下不支持 cls token")
            token_count = height * width
            output_ndim = 4
        else:
            batch_size, token_count, _channels = x.shape
            output_ndim = 3
            height = width = int(math.sqrt(token_count - cls_token_count))

        qkv = self.qkv(x).reshape(batch_size, token_count, 3, self.num_heads, -1)
        q, k, v = qkv.permute(2, 0, 3, 1, 4).unbind(0)
        q, k = self._apply_rope(q, k)
        x = F.scaled_dot_product_attention(q, k, v)

        if output_ndim == 4:
            x = x.view(batch_size, self.num_heads, height, width, -1).permute(0, 2, 3, 1, 4).reshape(batch_size, height, width, -1)
        else:
            x = x.view(batch_size, self.num_heads, token_count, -1).permute(0, 2, 1, 3).reshape(batch_size, token_count, -1)
        return self.proj(x)


class VisionBlock(nn.Module):
    """支持窗口 attention 的 ViT block。"""

    def __init__(
        self,
        dim: int,
        num_heads: int,
        mlp_ratio: float = 4.0,
        qkv_bias: bool = True,
        drop_path: float = 0.0,
        norm_layer: Callable[..., nn.Module] = nn.LayerNorm,
        act_layer: Callable[..., nn.Module] = nn.GELU,
        window_size: int = 0,
        input_size: tuple[int, int] | None = None,
        use_rope: bool = False,
        rope_pt_size: tuple[int, int] | None = None,
        rope_interp: bool = False,
        cls_token: bool = False,
        dropout: float = 0.0,
        init_values: float | None = None,
    ) -> None:
        super().__init__()
        self.norm1 = norm_layer(dim)
        attention_input_size = input_size if window_size == 0 else (window_size, window_size)
        self.attn = VisionAttention(
            dim,
            num_heads=num_heads,
            qkv_bias=qkv_bias,
            input_size=attention_input_size,
            use_rope=use_rope,
            rope_pt_size=rope_pt_size,
            rope_interp=rope_interp,
            cls_token=cls_token,
        )
        self.ls1 = LayerScale(dim, init_values=init_values) if init_values else nn.Identity()
        self.drop_path = DropPath(drop_path) if drop_path > 0.0 else nn.Identity()

        self.norm2 = norm_layer(dim)
        self.mlp = VisionMlp(in_features=dim, hidden_features=int(dim * mlp_ratio), act_layer=act_layer, drop=dropout)
        self.ls2 = LayerScale(dim, init_values=init_values) if init_values else nn.Identity()
        self.dropout = nn.Dropout(dropout)
        self.window_size = window_size

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        shortcut = x
        x = self.norm1(x)
        if self.window_size > 0:
            height, width = x.shape[1], x.shape[2]
            x, padded_hw = window_partition(x, self.window_size)

        x = self.ls1(self.attn(x))
        if self.window_size > 0:
            x = window_unpartition(x, self.window_size, padded_hw, (height, width))

        x = shortcut + self.dropout(self.drop_path(x))
        x = x + self.dropout(self.drop_path(self.ls2(self.mlp(self.norm2(x)))))
        return x


class ViT(nn.Module):
    """SAM3 interactive 需要的 ViT 主干。"""

    def __init__(
        self,
        img_size: int = 1008,
        patch_size: int = 14,
        in_chans: int = 3,
        embed_dim: int = 1024,
        depth: int = 32,
        num_heads: int = 16,
        mlp_ratio: float = 4.625,
        qkv_bias: bool = True,
        drop_path_rate: float = 0.0,
        norm_layer: Callable[..., nn.Module] | str = "LayerNorm",
        act_layer: Callable[..., nn.Module] = nn.GELU,
        use_abs_pos: bool = True,
        tile_abs_pos: bool = True,
        window_size: int = 24,
        global_att_blocks: tuple[int, ...] = (7, 15, 23, 31),
        use_rope: bool = True,
        rope_pt_size: int | None = None,
        use_interp_rope: bool = True,
        pretrain_img_size: int = 336,
        pretrain_use_cls_token: bool = True,
        retain_cls_token: bool = False,
        dropout: float = 0.0,
        return_interm_layers: bool = False,
        init_values: float | None = None,
        ln_pre: bool = True,
        ln_post: bool = False,
        bias_patch_embed: bool = True,
        use_act_checkpoint: bool = False,
        **_unused_kwargs: object,
    ) -> None:
        super().__init__()
        self.pretrain_use_cls_token = bool(pretrain_use_cls_token)
        self.retain_cls_token = bool(retain_cls_token)
        window_block_indexes = [index for index in range(depth) if index not in global_att_blocks]
        self.full_attn_ids = list(global_att_blocks)
        if isinstance(norm_layer, str):
            norm_layer_cls = getattr(nn, norm_layer)

            def norm_layer(dim: int) -> nn.Module:
                return norm_layer_cls(dim, eps=1e-5)

        if self.retain_cls_token:
            if not self.pretrain_use_cls_token:
                raise ValueError("retain_cls_token=True 时要求 pretrain_use_cls_token=True")
            if len(window_block_indexes) != 0:
                raise ValueError("带 cls token 的配置当前不支持窗口 attention")
            scale = embed_dim**-0.5
            self.class_embedding = nn.Parameter(scale * torch.randn(1, 1, embed_dim))

        self.patch_embed = PatchEmbed(
            kernel_size=(patch_size, patch_size),
            stride=(patch_size, patch_size),
            in_chans=in_chans,
            embed_dim=embed_dim,
            bias=bias_patch_embed,
        )
        self.tile_abs_pos = bool(tile_abs_pos)
        self.use_abs_pos = bool(use_abs_pos)
        if self.tile_abs_pos and not self.use_abs_pos:
            raise ValueError("tile_abs_pos=True 时必须启用绝对位置编码")

        if self.use_abs_pos:
            num_patches = (pretrain_img_size // patch_size) * (pretrain_img_size // patch_size)
            num_positions = num_patches + 1 if self.pretrain_use_cls_token else num_patches
            self.pos_embed = nn.Parameter(torch.zeros(1, num_positions, embed_dim))
        else:
            self.pos_embed = None

        dpr = [value.item() for value in torch.linspace(0, drop_path_rate, depth)]
        self.patch_size = patch_size
        self.blocks = nn.ModuleList()
        for index in range(depth):
            self.blocks.append(
                VisionBlock(
                    dim=embed_dim,
                    num_heads=num_heads,
                    mlp_ratio=mlp_ratio,
                    qkv_bias=qkv_bias,
                    drop_path=dpr[index],
                    norm_layer=norm_layer,
                    act_layer=act_layer,
                    window_size=window_size if index in window_block_indexes else 0,
                    input_size=(img_size // patch_size, img_size // patch_size),
                    use_rope=use_rope,
                    rope_pt_size=((window_size, window_size) if rope_pt_size is None else (rope_pt_size, rope_pt_size)),
                    rope_interp=use_interp_rope,
                    cls_token=self.retain_cls_token,
                    dropout=dropout,
                    init_values=init_values,
                )
            )
        self.return_interm_layers = bool(return_interm_layers)
        self.channel_list = [embed_dim] * len(self.full_attn_ids) if self.return_interm_layers else [embed_dim]
        self.ln_pre = norm_layer(embed_dim) if ln_pre else nn.Identity()
        self.ln_post = norm_layer(embed_dim) if ln_post else nn.Identity()
        self.use_act_checkpoint = bool(use_act_checkpoint)

        if self.pos_embed is not None:
            nn.init.trunc_normal_(self.pos_embed, std=0.02)
        self.apply(self._init_weights)

    @staticmethod
    def _init_weights(module: nn.Module) -> None:
        if isinstance(module, nn.Linear):
            nn.init.trunc_normal_(module.weight, std=0.02)
            if module.bias is not None:
                nn.init.constant_(module.bias, 0)
        elif isinstance(module, nn.LayerNorm):
            nn.init.constant_(module.bias, 0)
            nn.init.constant_(module.weight, 1.0)

    def forward(self, x: torch.Tensor) -> list[torch.Tensor]:
        x = self.patch_embed(x)
        height, width = x.shape[1], x.shape[2]
        cls_token_count = 0
        if self.retain_cls_token:
            x = torch.cat([self.class_embedding, x.flatten(1, 2)], dim=1)
            cls_token_count = 1
        if self.pos_embed is not None:
            x = x + get_abs_pos(
                self.pos_embed,
                self.pretrain_use_cls_token,
                (height, width),
                self.retain_cls_token,
                tiling=self.tile_abs_pos,
            )
        x = self.ln_pre(x)

        outputs: list[torch.Tensor] = []
        for index, block in enumerate(self.blocks):
            if self.use_act_checkpoint and self.training:
                x = checkpoint.checkpoint(block, x, use_reentrant=False)
            else:
                x = block(x)
            if (index == self.full_attn_ids[-1]) or (self.return_interm_layers and index in self.full_attn_ids):
                if index == self.full_attn_ids[-1]:
                    x = self.ln_post(x)
                feats = x[:, cls_token_count:]
                if feats.ndim == 4:
                    feats = feats.permute(0, 3, 1, 2)
                else:
                    spatial_size = int(math.sqrt(feats.shape[1]))
                    feats = feats.reshape(feats.shape[0], spatial_size, spatial_size, feats.shape[-1]).permute(0, 3, 1, 2)
                outputs.append(feats)
        return outputs

    def set_imgsz(self, imgsz: list[int] = [1008, 1008]) -> None:
        for block in self.blocks:
            if block.window_size != 0:
                continue
            block.attn._setup_rope_freqs(input_size=(imgsz[0] // self.patch_size, imgsz[1] // self.patch_size))


class Sam3DualViTDetNeck(nn.Module):
    """把 ViT 特征映射成 SAM3/SAM2 兼容 FPN 输出。"""

    def __init__(
        self,
        trunk: nn.Module,
        position_encoding: nn.Module,
        d_model: int,
        scale_factors: tuple[float, ...] = (4.0, 2.0, 1.0, 0.5),
        add_sam2_neck: bool = False,
    ) -> None:
        super().__init__()
        self.trunk = trunk
        self.position_encoding = position_encoding
        self.convs = nn.ModuleList()
        self.sam2_convs = None
        self.scale_factors = scale_factors
        dim = self.trunk.channel_list[-1]

        for scale in scale_factors:
            current = nn.Sequential()
            if scale == 4.0:
                current.add_module("dconv_2x2_0", nn.ConvTranspose2d(dim, dim // 2, kernel_size=2, stride=2))
                current.add_module("gelu", nn.GELU())
                current.add_module("dconv_2x2_1", nn.ConvTranspose2d(dim // 2, dim // 4, kernel_size=2, stride=2))
                out_dim = dim // 4
            elif scale == 2.0:
                current.add_module("dconv_2x2", nn.ConvTranspose2d(dim, dim // 2, kernel_size=2, stride=2))
                out_dim = dim // 2
            elif scale == 1.0:
                out_dim = dim
            elif scale == 0.5:
                current.add_module("maxpool_2x2", nn.MaxPool2d(kernel_size=2, stride=2))
                out_dim = dim
            else:
                raise NotImplementedError(f"暂不支持 scale_factor={scale}")
            current.add_module("conv_1x1", nn.Conv2d(out_dim, d_model, kernel_size=1, bias=True))
            current.add_module("conv_3x3", nn.Conv2d(d_model, d_model, kernel_size=3, padding=1, bias=True))
            self.convs.append(current)

        if add_sam2_neck:
            import copy

            self.sam2_convs = copy.deepcopy(self.convs)

    def sam_forward_feature_levels(
        self,
        x: torch.Tensor,
        convs: nn.ModuleList,
    ) -> tuple[list[torch.Tensor], list[torch.Tensor]]:
        outs: list[torch.Tensor] = []
        poss: list[torch.Tensor] = []
        for conv in convs:
            feat = conv(x)
            outs.append(feat)
            poss.append(self.position_encoding(feat).to(feat.dtype))
        return outs, poss

    def forward(
        self,
        tensor_list: torch.Tensor,
    ) -> tuple[list[torch.Tensor], list[torch.Tensor], list[torch.Tensor] | None, list[torch.Tensor] | None]:
        xs = self.trunk(tensor_list)
        x = xs[-1]
        sam3_out, sam3_pos = self.sam_forward_feature_levels(x, self.convs)
        if self.sam2_convs is None:
            return sam3_out, sam3_pos, None, None
        sam2_out, sam2_pos = self.sam_forward_feature_levels(x, self.sam2_convs)
        return sam3_out, sam3_pos, sam2_out, sam2_pos

    def set_imgsz(self, imgsz: list[int] = [1008, 1008]) -> None:
        self.trunk.set_imgsz(imgsz)


class SAM3VisualBackbone(nn.Module):
    """只保留视觉分支的 SAM3 backbone 包装。"""

    def __init__(self, vision_backbone: Sam3DualViTDetNeck, scalp: int = 1) -> None:
        super().__init__()
        self.vision_backbone = vision_backbone
        self.scalp = int(scalp)

    def forward_image(self, samples: torch.Tensor) -> dict[str, object]:
        sam3_features, sam3_pos, sam2_features, sam2_pos = self.vision_backbone.forward(samples)
        if self.scalp > 0:
            sam3_features = sam3_features[: -self.scalp]
            sam3_pos = sam3_pos[: -self.scalp]
            if sam2_features is not None and sam2_pos is not None:
                sam2_features = sam2_features[: -self.scalp]
                sam2_pos = sam2_pos[: -self.scalp]

        sam2_output = None
        if sam2_features is not None and sam2_pos is not None:
            sam2_output = {
                "vision_features": sam2_features[-1],
                "vision_pos_enc": sam2_pos,
                "backbone_fpn": sam2_features,
            }

        return {
            "vision_features": sam3_features[-1],
            "vision_pos_enc": sam3_pos,
            "backbone_fpn": sam3_features,
            "sam2_backbone_out": sam2_output,
        }

    def set_imgsz(self, imgsz: list[int] = [1008, 1008]) -> None:
        self.vision_backbone.set_imgsz(imgsz)


__all__ = [
    "PositionEmbeddingSine",
    "SAM3VisualBackbone",
    "Sam3DualViTDetNeck",
    "ViT",
]
