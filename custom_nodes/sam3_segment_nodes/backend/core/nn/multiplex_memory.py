"""SAM3.1 Multiplex mask memory encoder。"""

from __future__ import annotations

import math

import torch
from torch import nn
import torch.nn.functional as F

from .common import DropPath, LayerNorm2d, clone_module_list
from .vision_backbone import PositionEmbeddingSine


class Sam3MultiplexMaskDownsampler(nn.Module):
    """把 16 个对象 mask 和条件位压缩到 stride-14 特征空间。"""

    def __init__(
        self,
        *,
        embed_dim: int = 256,
        kernel_size: int = 3,
        stride: int = 2,
        padding: int = 1,
        total_stride: int = 16,
        interpol_size: tuple[int, int] = (1152, 1152),
        multiplex_count: int = 16,
        starting_out_channels: int = 4,
        input_channel_multiplier: int = 2,
    ) -> None:
        super().__init__()
        layer_count = int(math.log2(total_stride) // math.log2(stride))
        if stride**layer_count != total_stride:
            raise ValueError("mask downsampler 的 stride 不能整除 total_stride")
        input_channels = multiplex_count * input_channel_multiplier
        output_channels = starting_out_channels
        layers: list[nn.Module] = []
        for _ in range(layer_count):
            output_channels *= stride**2
            layers.extend(
                (
                    nn.Conv2d(
                        input_channels,
                        output_channels,
                        kernel_size=kernel_size,
                        stride=stride,
                        padding=padding,
                    ),
                    LayerNorm2d(output_channels),
                    nn.GELU(),
                )
            )
            input_channels = output_channels
        layers.append(nn.Conv2d(output_channels, embed_dim, kernel_size=1))
        self.encoder = nn.Sequential(*layers)
        self.multiplex_count = multiplex_count
        self.interpol_size = interpol_size

    def forward(self, masks: torch.Tensor) -> torch.Tensor:
        """插值到训练分辨率后编码 mask channel。"""

        encoder_dtype = next(self.encoder.parameters()).dtype
        if tuple(masks.shape[-2:]) != self.interpol_size:
            masks = F.interpolate(
                masks.float(),
                size=self.interpol_size,
                mode="bilinear",
                align_corners=False,
                antialias=True,
            )
        masks = masks.to(dtype=encoder_dtype)
        return self.encoder(masks)


class Sam3MultiplexCXBlock(nn.Module):
    """与 SAM3.1 checkpoint 对齐的 ConvNeXt fuser block。"""

    def __init__(
        self,
        *,
        dim: int = 256,
        kernel_size: int = 7,
        padding: int = 3,
        drop_path: float = 0.0,
        layer_scale_init_value: float = 1e-6,
    ) -> None:
        super().__init__()
        self.dwconv = nn.Conv2d(
            dim,
            dim,
            kernel_size=kernel_size,
            padding=padding,
            groups=dim,
        )
        self.norm = LayerNorm2d(dim, eps=1e-6)
        self.pwconv1 = nn.Linear(dim, 4 * dim)
        self.act = nn.GELU()
        self.pwconv2 = nn.Linear(4 * dim, dim)
        self.gamma = nn.Parameter(
            layer_scale_init_value * torch.ones(dim)
        )
        self.drop_path = (
            DropPath(drop_path) if drop_path > 0 else nn.Identity()
        )

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        residual = value
        value = self.dwconv(value)
        value = self.norm(value)
        value = value.permute(0, 2, 3, 1)
        value = self.pwconv2(self.act(self.pwconv1(value)))
        value = value * self.gamma
        value = value.permute(0, 3, 1, 2)
        return residual + self.drop_path(value)


class Sam3MultiplexFuser(nn.Module):
    """顺序执行同构 memory fuser blocks。"""

    def __init__(self, *, layer: nn.Module, layer_count: int) -> None:
        super().__init__()
        self.proj = nn.Identity()
        self.layers = clone_module_list(layer, layer_count)

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        value = self.proj(value)
        for layer in self.layers:
            value = layer(value)
        return value


class Sam3MultiplexMaskEncoder(nn.Module):
    """融合当前 propagation 图像特征与多对象 mask memory。"""

    def __init__(
        self,
        *,
        mask_downsampler: Sam3MultiplexMaskDownsampler,
        fuser: Sam3MultiplexFuser,
        position_encoding: nn.Module,
        input_dim: int = 256,
        output_dim: int = 256,
    ) -> None:
        super().__init__()
        self.mask_downsampler = mask_downsampler
        self.pix_feat_proj = nn.Conv2d(input_dim, input_dim, kernel_size=1)
        self.fuser = fuser
        self.position_encoding = position_encoding
        self.out_proj: nn.Module = nn.Identity()
        if output_dim != input_dim:
            self.out_proj = nn.Conv2d(input_dim, output_dim, kernel_size=1)

    def forward(
        self,
        pixel_features: torch.Tensor,
        masks: torch.Tensor,
        *,
        skip_mask_sigmoid: bool = False,
    ) -> dict[str, object]:
        """编码一帧 mask memory 并返回空间位置编码。"""

        if not skip_mask_sigmoid:
            masks = masks.sigmoid()
        encoded_masks = self.mask_downsampler(masks)
        pixel_features = pixel_features.to(encoded_masks.device)
        memory = self.pix_feat_proj(pixel_features) + encoded_masks
        memory = self.out_proj(self.fuser(memory))
        position = self.position_encoding(memory).to(memory.dtype)
        return {
            "vision_features": memory,
            "vision_pos_enc": [position],
        }


def build_sam3_multiplex_mask_encoder(
    *,
    multiplex_count: int = 16,
) -> Sam3MultiplexMaskEncoder:
    """按 SAM3.1 multiplex 固定结构构造 mask memory encoder。"""

    return Sam3MultiplexMaskEncoder(
        mask_downsampler=Sam3MultiplexMaskDownsampler(
            multiplex_count=multiplex_count,
        ),
        fuser=Sam3MultiplexFuser(
            layer=Sam3MultiplexCXBlock(),
            layer_count=2,
        ),
        position_encoding=PositionEmbeddingSine(
            num_pos_feats=256,
            normalize=True,
            scale=None,
            temperature=10000,
        ),
    )


__all__ = [
    "Sam3MultiplexMaskEncoder",
    "build_sam3_multiplex_mask_encoder",
]
