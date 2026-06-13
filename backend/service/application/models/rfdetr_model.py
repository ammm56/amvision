"""RF-DETR 项目内实现。对齐参考源码 LWDETR + Transformer + MSDeformAttn 架构。"""

from __future__ import annotations

import copy
import math
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from backend.service.application.errors import ServiceConfigurationError


# -- ViT Backbone --


class PatchEmbed(nn.Module):
    def __init__(
        self,
        img_size: int = 518,
        patch_size: int = 14,
        in_chans: int = 3,
        embed_dim: int = 384,
    ) -> None:
        super().__init__()
        self.img_size = img_size
        self.patch_size = patch_size
        self.num_patches = (img_size // patch_size) ** 2
        self.proj = nn.Conv2d(
            in_chans,
            embed_dim,
            kernel_size=patch_size,
            stride=patch_size,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.proj(x).flatten(2).transpose(1, 2)


class RfdetrAttention(nn.Module):
    def __init__(
        self,
        dim: int,
        num_heads: int = 6,
        qkv_bias: bool = True,
        attn_drop: float = 0.0,
        proj_drop: float = 0.0,
    ) -> None:
        super().__init__()
        self.num_heads = num_heads
        self.head_dim = dim // num_heads
        self.scale = self.head_dim**-0.5
        self.qkv = nn.Linear(dim, dim * 3, bias=qkv_bias)
        self.attn_drop = nn.Dropout(attn_drop)
        self.proj = nn.Linear(dim, dim)
        self.proj_drop = nn.Dropout(proj_drop)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch_size, token_count, channel_count = x.shape
        qkv = (
            self.qkv(x)
            .reshape(batch_size, token_count, 3, self.num_heads, self.head_dim)
            .permute(2, 0, 3, 1, 4)
        )
        q, k, v = qkv.unbind(0)
        attn = (q @ k.transpose(-2, -1)) * self.scale
        attn = attn.softmax(dim=-1)
        attn = self.attn_drop(attn)
        x = (attn @ v).transpose(1, 2).reshape(batch_size, token_count, channel_count)
        return self.proj_drop(self.proj(x))


class RfdetrMlp(nn.Module):
    def __init__(
        self,
        in_features: int,
        hidden_features: int | None = None,
        out_features: int | None = None,
        act_layer: type = nn.GELU,
        drop: float = 0.0,
    ) -> None:
        super().__init__()
        out_features = out_features or in_features
        hidden_features = hidden_features or in_features * 4
        self.fc1 = nn.Linear(in_features, hidden_features)
        self.act = act_layer()
        self.fc2 = nn.Linear(hidden_features, out_features)
        self.drop = nn.Dropout(drop)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.drop(self.fc2(self.drop(self.act(self.fc1(x)))))


class _DropPath(nn.Module):
    def __init__(self, drop_prob: float = 0.0) -> None:
        super().__init__()
        self.drop_prob = drop_prob

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.drop_prob == 0.0 or not self.training:
            return x
        keep_prob = 1.0 - self.drop_prob
        random_shape = (x.shape[0],) + (1,) * (x.ndim - 1)
        random_tensor = torch.rand(
            random_shape,
            dtype=x.dtype,
            device=x.device,
        )
        return x.div(keep_prob) * (keep_prob + random_tensor).floor_()


class RfdetrBlock(nn.Module):
    def __init__(
        self,
        dim: int,
        num_heads: int,
        mlp_ratio: float = 4.0,
        qkv_bias: bool = True,
        drop: float = 0.0,
        attn_drop: float = 0.0,
        drop_path: float = 0.0,
        layer_scale: float = 1.0,
    ) -> None:
        super().__init__()
        self.norm1 = nn.LayerNorm(dim, eps=1e-6)
        self.attn = RfdetrAttention(
            dim,
            num_heads,
            qkv_bias=qkv_bias,
            attn_drop=attn_drop,
            proj_drop=drop,
        )
        self.drop_path = _DropPath(drop_path) if drop_path > 0.0 else nn.Identity()
        self.norm2 = nn.LayerNorm(dim, eps=1e-6)
        self.mlp = RfdetrMlp(dim, int(dim * mlp_ratio), drop=drop)
        self.ls1 = nn.Parameter(torch.ones(dim) * layer_scale)
        self.ls2 = nn.Parameter(torch.ones(dim) * layer_scale)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.drop_path(self.ls1 * self.attn(self.norm1(x)))
        x = x + self.drop_path(self.ls2 * self.mlp(self.norm2(x)))
        return x


class RfdetrViTBackbone(nn.Module):
    def __init__(
        self,
        *,
        img_size: int = 518,
        patch_size: int = 14,
        in_chans: int = 3,
        embed_dim: int = 384,
        depth: int = 12,
        num_heads: int = 6,
        mlp_ratio: float = 4.0,
        qkv_bias: bool = True,
        drop_rate: float = 0.0,
        attn_drop_rate: float = 0.0,
        drop_path_rate: float = 0.0,
        layer_scale: float = 1.0,
        out_feature_indexes: list[int] | None = None,
    ) -> None:
        super().__init__()
        self.embed_dim = embed_dim
        self.patch_size = patch_size
        self.out_feature_indexes = out_feature_indexes or [2, 5, 8, 11]
        self.patch_embed = PatchEmbed(
            img_size=img_size,
            patch_size=patch_size,
            in_chans=in_chans,
            embed_dim=embed_dim,
        )
        num_patches = (img_size // patch_size) ** 2
        self.cls_token = nn.Parameter(torch.zeros(1, 1, embed_dim))
        self.pos_embed = nn.Parameter(torch.zeros(1, num_patches + 1, embed_dim))
        self.pos_drop = nn.Dropout(p=drop_rate)
        drop_path_rates = [item.item() for item in torch.linspace(0, drop_path_rate, depth)]
        self.blocks = nn.ModuleList(
            [
                RfdetrBlock(
                    dim=embed_dim,
                    num_heads=num_heads,
                    mlp_ratio=mlp_ratio,
                    qkv_bias=qkv_bias,
                    drop=drop_rate,
                    attn_drop=attn_drop_rate,
                    drop_path=drop_path_rates[index],
                    layer_scale=layer_scale,
                )
                for index in range(depth)
            ]
        )
        self.norm = nn.LayerNorm(embed_dim, eps=1e-6)
        self._init_weights()

    def _init_weights(self) -> None:
        nn.init.trunc_normal_(self.pos_embed, std=0.02)
        nn.init.trunc_normal_(self.cls_token, std=0.02)
        self.apply(_init_vit_weights)

    def _interp_pos(self, x: torch.Tensor, hp: int, wp: int) -> torch.Tensor:
        token_count = x.shape[1] - 1
        position_count = self.pos_embed.shape[1] - 1
        if token_count == position_count and hp == wp:
            return self.pos_embed
        position_embed = (
            self.pos_embed[:, 1:]
            .reshape(
                1,
                int(math.sqrt(position_count)),
                int(math.sqrt(position_count)),
                self.embed_dim,
            )
            .permute(0, 3, 1, 2)
        )
        position_height = hp // self.patch_size
        position_width = wp // self.patch_size
        position_embed = (
            F.interpolate(
                position_embed,
                size=(position_height, position_width),
                mode="bicubic",
                align_corners=False,
            )
            .permute(0, 2, 3, 1)
            .reshape(1, -1, self.embed_dim)
        )
        return torch.cat((self.pos_embed[:, :1], position_embed), dim=1)

    def forward(self, x: torch.Tensor) -> tuple[list[torch.Tensor], list[torch.Tensor]]:
        batch_size, _, image_height, image_width = x.shape
        x = self.patch_embed(x)
        x = torch.cat((self.cls_token.expand(batch_size, -1, -1), x), dim=1)
        x = self.pos_drop(x + self._interp_pos(x, image_height, image_width))
        feats: list[torch.Tensor] = []
        masks: list[torch.Tensor] = []
        for index, block in enumerate(self.blocks):
            x = block(x)
            if index in self.out_feature_indexes:
                feature_height = image_height // self.patch_size
                feature_width = image_width // self.patch_size
                feats.append(
                    self.norm(x[:, 1:])
                    .transpose(1, 2)
                    .reshape(batch_size, self.embed_dim, feature_height, feature_width)
                )
                masks.append(
                    torch.zeros(
                        (batch_size, feature_height, feature_width),
                        dtype=torch.bool,
                        device=x.device,
                    )
                )
        return feats, masks


def _init_vit_weights(module: nn.Module) -> None:
    if isinstance(module, nn.Linear):
        nn.init.trunc_normal_(module.weight, std=0.02)
        if module.bias is not None:
            nn.init.zeros_(module.bias)
    elif isinstance(module, nn.LayerNorm):
        nn.init.zeros_(module.bias)
        nn.init.ones_(module.weight)


# -- Projector --


class MultiScaleProjector(nn.Module):
    def __init__(
        self,
        in_channels: list[int] | None = None,
        out_channels: int = 256,
        scale_factors: list[float] | None = None,
    ) -> None:
        super().__init__()
        in_channels = in_channels or [384] * 4
        self.scale_factors = scale_factors or [2.0, 1.0, 0.5, 0.25]
        self.projections = nn.ModuleList(
            [nn.Conv2d(channel_count, out_channels, 1) for channel_count in in_channels]
        )

    def forward(self, feats: list[torch.Tensor]) -> list[torch.Tensor]:
        projected_features: list[torch.Tensor] = []
        for feature, projection, scale_factor in zip(
            feats,
            self.projections,
            self.scale_factors,
            strict=True,
        ):
            projected = projection(feature)
            if scale_factor != 1.0:
                projected = F.interpolate(
                    projected,
                    size=(
                        max(1, int(feature.shape[2] * scale_factor)),
                        max(1, int(feature.shape[3] * scale_factor)),
                    ),
                    mode="bilinear",
                    align_corners=False,
                )
            projected_features.append(projected)
        return projected_features


# -- MLP --


class MLP(nn.Module):
    def __init__(
        self,
        input_dim: int,
        hidden_dim: int,
        output_dim: int,
        num_layers: int,
    ) -> None:
        super().__init__()
        self.num_layers = num_layers
        dims = [input_dim] + [hidden_dim] * (num_layers - 1) + [output_dim]
        self.layers = nn.ModuleList(
            nn.Linear(dims[index], dims[index + 1]) for index in range(num_layers)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for index, layer_module in enumerate(self.layers):
            if index < self.num_layers - 1:
                x = F.relu(layer_module(x))
            else:
                x = layer_module(x)
        return x


# -- Position encoding --


def gen_sineembed(pos_tensor: torch.Tensor, dim: int = 128) -> torch.Tensor:
    scale = 2.0 * math.pi
    dim_t = torch.arange(dim, dtype=pos_tensor.dtype, device=pos_tensor.device)
    dim_t = 10000 ** (2 * (dim_t // 2) / dim)
    x_embed = pos_tensor[:, :, 0] * scale
    y_embed = pos_tensor[:, :, 1] * scale
    px = x_embed[:, :, None] / dim_t
    py = y_embed[:, :, None] / dim_t
    px = torch.stack((px[:, :, 0::2].sin(), px[:, :, 1::2].cos()), dim=3).flatten(2)
    py = torch.stack((py[:, :, 0::2].sin(), py[:, :, 1::2].cos()), dim=3).flatten(2)
    if pos_tensor.size(-1) == 4:
        width_embed = pos_tensor[:, :, 2] * scale
        height_embed = pos_tensor[:, :, 3] * scale
        pw = width_embed[:, :, None] / dim_t
        ph = height_embed[:, :, None] / dim_t
        pw = torch.stack((pw[:, :, 0::2].sin(), pw[:, :, 1::2].cos()), dim=3).flatten(2)
        ph = torch.stack((ph[:, :, 0::2].sin(), ph[:, :, 1::2].cos()), dim=3).flatten(2)
        return torch.cat((py, px, pw, ph), dim=2)
    return torch.cat((py, px), dim=2)


# -- MSDeformAttn (aligned with reference call signature) --


class MSDeformAttn(nn.Module):
    def __init__(
        self,
        d_model: int = 256,
        n_levels: int = 4,
        n_heads: int = 8,
        n_points: int = 4,
    ) -> None:
        super().__init__()
        self.d_model = d_model
        self.n_levels = n_levels
        self.n_heads = n_heads
        self.n_points = n_points
        self.sampling_offsets = nn.Linear(d_model, n_heads * n_levels * n_points * 2)
        self.attention_weights = nn.Linear(d_model, n_heads * n_levels * n_points)
        self.value_proj = nn.Linear(d_model, d_model)
        self.output_proj = nn.Linear(d_model, d_model)
        self._reset_parameters()

    def _reset_parameters(self) -> None:
        nn.init.constant_(self.sampling_offsets.weight.data, 0.0)
        nn.init.constant_(self.sampling_offsets.bias.data, 0.0)
        nn.init.constant_(self.attention_weights.weight.data, 0.0)
        nn.init.constant_(self.attention_weights.bias.data, 0.0)
        nn.init.xavier_uniform_(self.value_proj.weight.data)
        nn.init.constant_(self.value_proj.bias.data, 0.0)
        nn.init.xavier_uniform_(self.output_proj.weight.data)
        nn.init.constant_(self.output_proj.bias.data, 0.0)

    def forward(
        self,
        query: torch.Tensor,
        reference_points: torch.Tensor,
        value: torch.Tensor,
        spatial_shapes: torch.Tensor,
        level_start_index: torch.Tensor,
        memory_key_padding_mask: torch.Tensor | None = None,
        input_spatial_shapes_hw: list | None = None,
    ) -> torch.Tensor:
        batch_size, query_count, _ = query.shape
        _, value_count, _ = value.shape
        head_count = self.n_heads
        level_count = self.n_levels
        point_count = self.n_points
        value = self.value_proj(value).view(batch_size, value_count, head_count, -1)
        offsets = self.sampling_offsets(query).view(
            batch_size,
            query_count,
            head_count,
            level_count,
            point_count,
            2,
        )
        attn = self.attention_weights(query).view(
            batch_size,
            query_count,
            head_count,
            level_count * point_count,
        )
        attn = F.softmax(attn, dim=-1).view(
            batch_size,
            query_count,
            head_count,
            level_count,
            point_count,
        )
        if reference_points.shape[-1] == 2:
            reference_anchor = reference_points[:, :, None, :, None, :]
        else:
            reference_anchor = reference_points[:, :, None, None, None, :2]
        normalizer = torch.stack(
            [spatial_shapes[:, 1], spatial_shapes[:, 0]],
            dim=1,
        ).float()
        sampling_locs = reference_anchor + offsets / normalizer[
            None,
            None,
            None,
            :,
            None,
            :,
        ]
        head_dim = self.d_model // head_count
        output = torch.zeros(
            batch_size,
            query_count,
            head_count,
            head_dim,
            device=value.device,
            dtype=value.dtype,
        )
        for level in range(level_count):
            height = int(spatial_shapes[level, 0])
            width = int(spatial_shapes[level, 1])
            level_start = int(level_start_index[level])
            level_end = level_start + height * width
            level_value = (
                value[:, level_start:level_end]
                .reshape(batch_size, height, width, head_count, head_dim)
                .permute(0, 3, 4, 1, 2)
                .contiguous()
            )
            grid = (
                sampling_locs[:, :, :, level, :, :]
                .permute(0, 2, 1, 3, 4)
                .contiguous()
                * 2.0
                - 1.0
            )
            sampled = F.grid_sample(
                level_value.flatten(0, 1).float(),
                grid.flatten(0, 1).float(),
                mode="bilinear",
                padding_mode="zeros",
                align_corners=False,
            )
            sampled = sampled.reshape(
                batch_size,
                head_count,
                head_dim,
                query_count,
                point_count,
            ).permute(0, 3, 1, 4, 2)
            output = output + (sampled * attn[:, :, :, level, :, None]).sum(dim=3)
        return self.output_proj(output.reshape(batch_size, query_count, head_count * head_dim))


# -- Decoder Layer (aligned with reference forward_post) --


class RfdetrDecoderLayer(nn.Module):
    def __init__(
        self,
        d_model: int = 256,
        sa_nhead: int = 8,
        ca_nhead: int = 8,
        dim_feedforward: int = 1024,
        dropout: float = 0.0,
        group_detr: int = 1,
        n_levels: int = 4,
    ) -> None:
        super().__init__()
        self.self_attn = nn.MultiheadAttention(
            d_model,
            sa_nhead,
            dropout=dropout,
            batch_first=True,
        )
        self.cross_attn = MSDeformAttn(
            d_model=d_model,
            n_levels=n_levels,
            n_heads=ca_nhead,
        )
        self.linear1 = nn.Linear(d_model, dim_feedforward)
        self.linear2 = nn.Linear(dim_feedforward, d_model)
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.norm3 = nn.LayerNorm(d_model)
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)
        self.dropout3 = nn.Dropout(dropout)
        self.group_detr = group_detr
        self.nhead = ca_nhead

    @staticmethod
    def _with_pos_embed(tensor: torch.Tensor, pos: torch.Tensor | None) -> torch.Tensor:
        return tensor if pos is None else tensor + pos

    def forward(
        self,
        tgt: torch.Tensor,
        memory: torch.Tensor,
        query_pos: torch.Tensor | None,
        ref_pts: torch.Tensor,
        ss: torch.Tensor,
        lsi: torch.Tensor,
        mem_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        batch_size, query_count, _ = tgt.shape

        # Self-attn 训练时按 group_detr 拆分，保持和原实现一致。
        q = k = self._with_pos_embed(tgt, query_pos)
        v = tgt
        if self.training and self.group_detr > 1:
            group_query_count = query_count // self.group_detr
            q = torch.cat(q.split(group_query_count, dim=1), dim=0)
            k = torch.cat(k.split(group_query_count, dim=1), dim=0)
            v = torch.cat(v.split(group_query_count, dim=1), dim=0)
        tgt2 = self.self_attn(q, k, v)[0]
        if self.training and self.group_detr > 1:
            tgt2 = torch.cat(tgt2.split(batch_size, dim=0), dim=1)
        tgt = tgt + self.dropout1(tgt2)
        tgt = self.norm1(tgt)

        # Cross-attn 注入 query_pos，保持原有 ref_pts / memory 形状约定。
        tgt2 = self.cross_attn(self._with_pos_embed(tgt, query_pos), ref_pts, memory, ss, lsi, mem_mask)
        tgt = tgt + self.dropout2(tgt2)
        tgt = self.norm2(tgt)
        tgt2 = self.linear2(self.dropout3(F.relu(self.linear1(tgt))))
        tgt = tgt + self.dropout3(tgt2)
        tgt = self.norm3(tgt)
        return tgt


# -- Decoder (with ref_point_head, get_reference, refpoints_refine, return_intermediate) --


class RfdetrDecoder(nn.Module):
    def __init__(
        self,
        layer: nn.Module,
        num_layers: int,
        norm: nn.Module | None = None,
        return_intermediate: bool = True,
        d_model: int = 256,
        lite_refpoint_refine: bool = False,
        bbox_reparam: bool = True,
    ) -> None:
        super().__init__()
        self.layers = nn.ModuleList([copy.deepcopy(layer) for _ in range(num_layers)])
        self.num_layers = num_layers
        self.norm = norm
        self.return_intermediate = return_intermediate
        self.d_model = d_model
        self.lite_refpoint_refine = lite_refpoint_refine
        self.bbox_reparam = bbox_reparam
        self.ref_point_head = MLP(2 * d_model, d_model, d_model, 2)

    def _get_reference(
        self,
        ref_pts: torch.Tensor,
        valid_ratios: torch.Tensor | None,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        obj_center = ref_pts[..., :4]
        if valid_ratios is not None:
            ref_input = obj_center[:, :, None] * torch.cat([valid_ratios, valid_ratios], -1)[
                :,
                None,
            ]
        else:
            ref_input = obj_center[:, :, None]
        query_sine_embed = gen_sineembed(ref_input[:, :, 0, :], self.d_model // 2)
        query_pos = self.ref_point_head(query_sine_embed)
        return obj_center, ref_input, query_pos, query_sine_embed

    def _refpoints_refine(self, ref_unsigmoid: torch.Tensor, delta: torch.Tensor) -> torch.Tensor:
        if self.bbox_reparam:
            next_center_xy = delta[..., :2] * ref_unsigmoid[..., 2:] + ref_unsigmoid[..., :2]
            next_wh = delta[..., 2:].exp() * ref_unsigmoid[..., 2:]
            return torch.cat([next_center_xy, next_wh], dim=-1)
        return ref_unsigmoid + delta

    def forward(
        self,
        tgt: torch.Tensor,
        memory: torch.Tensor,
        pos: torch.Tensor,
        ref_pts: torch.Tensor,
        ss: torch.Tensor,
        lsi: torch.Tensor,
        valid_ratios: torch.Tensor | None = None,
        bbox_embed: nn.Module | None = None,
    ) -> tuple[torch.Tensor, list[torch.Tensor], list[torch.Tensor]]:
        intermediate: list[torch.Tensor] = []
        refpoints_list = [ref_pts]
        out = tgt
        refined_ref_pts = ref_pts
        for layer_index, layer in enumerate(self.layers):
            if not self.lite_refpoint_refine:
                _, _, query_pos, _ = self._get_reference(refined_ref_pts, valid_ratios)
            else:
                _, _, query_pos, _ = (
                    self._get_reference(refined_ref_pts, valid_ratios)
                    if layer_index == 0
                    else (None, None, None, None)
                )
            out = layer(out, memory, query_pos, refined_ref_pts, ss, lsi)
            if not self.lite_refpoint_refine and bbox_embed is not None:
                delta = bbox_embed(out)
                next_ref_pts = self._refpoints_refine(refined_ref_pts, delta)
                if layer_index != self.num_layers - 1:
                    refpoints_list.append(next_ref_pts)
                refined_ref_pts = next_ref_pts.detach()
            if self.return_intermediate:
                intermediate.append(self.norm(out) if self.norm is not None else out)
        if self.norm is not None and self.return_intermediate:
            intermediate[-1] = self.norm(out)
        return out, intermediate, refpoints_list


# -- Detection Head (class_embed with num_classes+1) --


class RfdetrDetectionHead(nn.Module):
    def __init__(self, hidden_dim: int, num_classes: int) -> None:
        super().__init__()
        head_class_count = num_classes + 1  # +1 for "no object" (aligns with reference build_model)
        self.class_embed = nn.Linear(hidden_dim, head_class_count)
        self.bbox_embed = MLP(hidden_dim, hidden_dim, 4, 3)
        prior_prob = 0.01
        self.class_embed.bias.data = torch.ones(head_class_count) * (
            -math.log((1 - prior_prob) / prior_prob)
        )
        for layer_module in self.bbox_embed.layers:
            if isinstance(layer_module, nn.Linear):
                nn.init.constant_(layer_module.bias.data, 0.0)
                nn.init.xavier_uniform_(layer_module.weight.data)
        nn.init.constant_(self.bbox_embed.layers[-1].bias.data, 0.0)
        nn.init.constant_(self.bbox_embed.layers[-1].weight.data, 0.0)

    def forward(self, hs: torch.Tensor, ref_unsigmoid: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        pred_logits = self.class_embed(hs)
        delta = self.bbox_embed(hs)
        ref_center_x = ref_unsigmoid[..., 0:1]
        ref_center_y = ref_unsigmoid[..., 1:2]
        ref_width = ref_unsigmoid[..., 2:3] if ref_unsigmoid.shape[-1] >= 4 else torch.full_like(ref_center_x, 0.05)
        ref_height = ref_unsigmoid[..., 3:4] if ref_unsigmoid.shape[-1] >= 4 else torch.full_like(ref_center_x, 0.05)
        center_x = delta[..., 0:1] * ref_width + ref_center_x
        center_y = delta[..., 1:2] * ref_height + ref_center_y
        width = torch.exp(delta[..., 2:3].clamp(max=4.0)) * ref_width
        height = torch.exp(delta[..., 3:4].clamp(max=4.0)) * ref_height
        return pred_logits, torch.cat([center_x, center_y, width, height], dim=-1)


# -- PostProcess (uses num_classes with +1) --


class RfdetrPostProcess(nn.Module):
    def __init__(self, num_select: int = 300) -> None:
        super().__init__()
        self.num_select = num_select

    def forward(self, outputs: dict[str, torch.Tensor], target_sizes: torch.Tensor) -> dict[str, torch.Tensor]:
        pred_logits = outputs["pred_logits"]
        pred_boxes = outputs["pred_boxes"]
        batch_size, query_count, class_count = pred_logits.shape
        probabilities = pred_logits.sigmoid()
        num_select = min(self.num_select, query_count * class_count)
        top_scores, top_indices = torch.topk(
            probabilities.view(batch_size, -1),
            num_select,
            dim=1,
        )
        top_boxes = top_indices // class_count
        top_labels = top_indices % class_count
        batch_indices = (
            torch.arange(batch_size, device=pred_logits.device)
            .unsqueeze(1)
            .expand(-1, num_select)
        )
        top_box_values = pred_boxes[batch_indices, top_boxes]
        image_heights, image_widths = target_sizes.unbind(1)
        scale_factors = torch.stack([image_widths, image_heights, image_widths, image_heights], dim=1).unsqueeze(1)
        scaled_boxes = top_box_values * scale_factors
        center_x, center_y, width, height = (
            scaled_boxes[..., 0],
            scaled_boxes[..., 1],
            scaled_boxes[..., 2],
            scaled_boxes[..., 3],
        )
        boxes_xyxy = torch.stack(
            [
                center_x - width / 2,
                center_y - height / 2,
                center_x + width / 2,
                center_y + height / 2,
            ],
            dim=-1,
        )
        return {"scores": top_scores, "labels": top_labels, "boxes_xyxy": boxes_xyxy}


# -- Complete Model --


class RfdetrModel(nn.Module):
    def __init__(
        self,
        *,
        backbone: nn.Module,
        projector: MultiScaleProjector,
        hidden_dim: int = 256,
        num_queries: int = 300,
        num_decoder_layers: int = 3,
        sa_nhead: int = 8,
        ca_nhead: int = 8,
        num_classes: int = 91,
        num_select: int = 300,
        group_detr: int = 1,
    ) -> None:
        super().__init__()
        self.backbone = backbone
        self.projector = projector
        self.hidden_dim = hidden_dim
        self.num_queries = num_queries
        self.group_detr = group_detr
        self.query_embed = nn.Embedding(num_queries * group_detr, hidden_dim * 2)
        self.refpoint_embed = nn.Embedding(num_queries * group_detr, 4)
        decoder_layer = RfdetrDecoderLayer(
            d_model=hidden_dim,
            sa_nhead=sa_nhead,
            ca_nhead=ca_nhead,
            group_detr=group_detr,
            n_levels=len(projector.projections),
        )
        self.decoder = RfdetrDecoder(
            decoder_layer,
            num_decoder_layers,
            nn.LayerNorm(hidden_dim),
            return_intermediate=True,
            d_model=hidden_dim,
            bbox_reparam=True,
        )
        self.detection_head = RfdetrDetectionHead(hidden_dim, num_classes)
        self.postprocess = RfdetrPostProcess(num_select=num_select)

    def forward(self, images: torch.Tensor) -> dict[str, Any]:
        feats, masks = self.backbone(images)
        projected_features = self.projector(feats)
        src_parts: list[torch.Tensor] = []
        pos_parts: list[torch.Tensor] = []
        spatial_shape_items: list[tuple[int, int]] = []
        for projected_feature, mask in zip(projected_features, masks, strict=True):
            batch_size, _, feature_height, feature_width = projected_feature.shape
            src_parts.append(projected_feature.flatten(2).permute(0, 2, 1))
            y_coords, x_coords = torch.meshgrid(
                torch.arange(feature_height, dtype=torch.float32, device=projected_feature.device),
                torch.arange(feature_width, dtype=torch.float32, device=projected_feature.device),
                indexing="ij",
            )
            pos_parts.append(
                gen_sineembed(
                    torch.stack([x_coords, y_coords], dim=-1)
                    .reshape(1, feature_height * feature_width, 2)
                    .repeat(batch_size, 1, 1),
                    dim=self.hidden_dim // 2,
                )
            )
            spatial_shape_items.append((feature_height, feature_width))

        memory = torch.cat(src_parts, dim=1)
        pos = torch.cat(pos_parts, dim=1)
        spatial_shapes = torch.tensor(spatial_shape_items, device=images.device)
        level_start_index = torch.cat(
            (
                spatial_shapes.new_zeros((1,)),
                spatial_shapes.prod(1).cumsum(0)[:-1],
            )
        )
        valid_ratios = _compute_valid_ratios(masks)
        active_group_count = self.group_detr if self.training else 1
        query_features = (
            self.query_embed.weight[: self.num_queries * active_group_count]
            .unsqueeze(0)
            .repeat(batch_size, 1, 1)
        )
        ref_points = (
            self.refpoint_embed.weight[: self.num_queries * active_group_count]
            .unsqueeze(0)
            .repeat(batch_size, 1, 1)
            .sigmoid()
        )
        target = query_features[:, :, : self.hidden_dim]
        _, intermediate, refpoints_list = self.decoder(
            target,
            memory,
            pos,
            ref_points,
            spatial_shapes,
            level_start_index,
            valid_ratios,
            self.detection_head.bbox_embed,
        )
        ref_unsigmoid = refpoints_list[-1] if len(refpoints_list) >= len(intermediate) else ref_points
        pred_logits = torch.stack(
            [self.detection_head(hidden_state, ref_unsigmoid)[0] for hidden_state in intermediate]
        )
        pred_boxes = torch.stack(
            [self.detection_head(hidden_state, ref_unsigmoid)[1] for hidden_state in intermediate]
        )
        aux_outputs = [
            {"pred_logits": pred_logits[index], "pred_boxes": pred_boxes[index]}
            for index in range(len(intermediate) - 1)
        ]
        return {
            "pred_logits": pred_logits[-1],
            "pred_boxes": pred_boxes[-1],
            "hs": intermediate,
            "aux_outputs": aux_outputs,
        }


def _compute_valid_ratios(masks: list[torch.Tensor]) -> torch.Tensor:
    valid_ratios: list[torch.Tensor] = []
    for mask in masks:
        _, feature_height, feature_width = mask.shape
        valid_width = (~mask[:, 0, :]).float().sum(dim=1) / feature_width
        valid_height = (~mask[:, :, 0]).float().sum(dim=1) / feature_height
        valid_ratios.append(torch.stack([valid_width, valid_height], dim=-1))
    return torch.stack(valid_ratios, dim=1)


_RF_SCALE = {
    "nano": {"hd": 256, "nq": 300, "ndl": 2, "san": 8, "can": 8, "gd": 1, "vd": 12, "ve": 384, "vh": 6, "is": 384, "ps": 14},
    "s": {"hd": 256, "nq": 300, "ndl": 3, "san": 8, "can": 8, "gd": 1, "vd": 12, "ve": 384, "vh": 6, "is": 512, "ps": 14},
    "m": {"hd": 256, "nq": 300, "ndl": 4, "san": 8, "can": 8, "gd": 1, "vd": 12, "ve": 384, "vh": 6, "is": 576, "ps": 14},
    "l": {"hd": 256, "nq": 300, "ndl": 4, "san": 8, "can": 8, "gd": 1, "vd": 12, "ve": 384, "vh": 6, "is": 704, "ps": 14},
    "x": {"hd": 256, "nq": 300, "ndl": 4, "san": 8, "can": 8, "gd": 1, "vd": 12, "ve": 384, "vh": 6, "is": 768, "ps": 14},
}


def build_rfdetr_model(
    *,
    model_scale: str = "nano",
    num_classes: int = 91,
    pretrained_path: str | None = None,
) -> RfdetrModel:
    config = _RF_SCALE.get(model_scale)
    if config is None:
        raise ServiceConfigurationError(f"RF-DETR 不支持 model_scale={model_scale}")
    backbone = RfdetrViTBackbone(
        img_size=config["is"],
        patch_size=config["ps"],
        embed_dim=config["ve"],
        depth=config["vd"],
        num_heads=config["vh"],
        out_feature_indexes=[2, 5, 8, 11],
    )
    projector = MultiScaleProjector(
        in_channels=[config["ve"]] * 4,
        out_channels=config["hd"],
        scale_factors=[2.0, 1.0, 0.5, 0.25],
    )
    model = RfdetrModel(
        backbone=backbone,
        projector=projector,
        hidden_dim=config["hd"],
        num_queries=config["nq"],
        num_decoder_layers=config["ndl"],
        sa_nhead=config["san"],
        ca_nhead=config["can"],
        num_classes=num_classes,
        group_detr=config["gd"],
    )
    if pretrained_path:
        load_rfdetr_pretrained(model, pretrained_path)
    return model


def load_rfdetr_pretrained(model: RfdetrModel, path: str) -> None:
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    state_dict = checkpoint.get("model", checkpoint.get("state_dict", checkpoint))
    filtered_state_dict = {}
    model_state_dict = model.state_dict()
    for key, value in state_dict.items():
        normalized_key = key.replace("model.", "").replace("module.", "")
        if normalized_key in model_state_dict and model_state_dict[normalized_key].shape == value.shape:
            filtered_state_dict[normalized_key] = value
    model.load_state_dict(filtered_state_dict, strict=False)


def _box_cxcywh_to_xyxy(boxes: torch.Tensor) -> torch.Tensor:
    center_x, center_y, width, height = boxes.unbind(-1)
    return torch.stack(
        [
            center_x - width / 2,
            center_y - height / 2,
            center_x + width / 2,
            center_y + height / 2,
        ],
        dim=-1,
    )


def sigmoid_focal_loss(
    inputs: torch.Tensor,
    targets: torch.Tensor,
    alpha: float = 0.25,
    gamma: float = 2.0,
) -> torch.Tensor:
    prob = inputs.sigmoid()
    ce = F.binary_cross_entropy_with_logits(inputs, targets, reduction="none")
    p_t = prob * targets + (1 - prob) * (1 - targets)
    loss = ce * ((1 - p_t) ** gamma)
    if alpha >= 0:
        loss = (alpha * targets + (1 - alpha) * (1 - targets)) * loss
    return loss.sum() / max(1, int(targets.sum()))
