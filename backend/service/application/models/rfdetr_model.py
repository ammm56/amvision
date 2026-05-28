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
    def __init__(self, img_size: int = 518, patch_size: int = 14, in_chans: int = 3, embed_dim: int = 384) -> None:
        super().__init__()
        self.img_size = img_size; self.patch_size = patch_size; self.num_patches = (img_size // patch_size) ** 2
        self.proj = nn.Conv2d(in_chans, embed_dim, kernel_size=patch_size, stride=patch_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.proj(x).flatten(2).transpose(1, 2)


class RfdetrAttention(nn.Module):
    def __init__(self, dim: int, num_heads: int = 6, qkv_bias: bool = True, attn_drop: float = 0.0, proj_drop: float = 0.0) -> None:
        super().__init__()
        self.num_heads = num_heads; self.head_dim = dim // num_heads; self.scale = self.head_dim ** -0.5
        self.qkv = nn.Linear(dim, dim * 3, bias=qkv_bias)
        self.attn_drop = nn.Dropout(attn_drop); self.proj = nn.Linear(dim, dim); self.proj_drop = nn.Dropout(proj_drop)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, self.head_dim).permute(2, 0, 3, 1, 4)
        q, k, v = qkv.unbind(0)
        attn = (q @ k.transpose(-2, -1)) * self.scale; attn = attn.softmax(dim=-1); attn = self.attn_drop(attn)
        x = (attn @ v).transpose(1, 2).reshape(B, N, C)
        return self.proj_drop(self.proj(x))


class RfdetrMlp(nn.Module):
    def __init__(self, in_features: int, hidden_features: int | None = None, out_features: int | None = None, act_layer: type = nn.GELU, drop: float = 0.0) -> None:
        super().__init__()
        out_features = out_features or in_features; hidden_features = hidden_features or in_features * 4
        self.fc1 = nn.Linear(in_features, hidden_features); self.act = act_layer()
        self.fc2 = nn.Linear(hidden_features, out_features); self.drop = nn.Dropout(drop)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.drop(self.fc2(self.drop(self.act(self.fc1(x)))))


class _DropPath(nn.Module):
    def __init__(self, drop_prob: float = 0.0) -> None:
        super().__init__(); self.drop_prob = drop_prob

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.drop_prob == 0.0 or not self.training: return x
        keep_prob = 1.0 - self.drop_prob
        return x.div(keep_prob) * (keep_prob + torch.rand((x.shape[0],) + (1,) * (x.ndim - 1), dtype=x.dtype, device=x.device)).floor_()


class RfdetrBlock(nn.Module):
    def __init__(self, dim: int, num_heads: int, mlp_ratio: float = 4.0, qkv_bias: bool = True, drop: float = 0.0, attn_drop: float = 0.0, drop_path: float = 0.0, layer_scale: float = 1.0) -> None:
        super().__init__()
        self.norm1 = nn.LayerNorm(dim, eps=1e-6); self.attn = RfdetrAttention(dim, num_heads, qkv_bias=qkv_bias, attn_drop=attn_drop, proj_drop=drop)
        self.drop_path = _DropPath(drop_path) if drop_path > 0.0 else nn.Identity()
        self.norm2 = nn.LayerNorm(dim, eps=1e-6); self.mlp = RfdetrMlp(dim, int(dim * mlp_ratio), drop=drop)
        self.ls1 = nn.Parameter(torch.ones(dim) * layer_scale); self.ls2 = nn.Parameter(torch.ones(dim) * layer_scale)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.drop_path(self.ls1 * self.attn(self.norm1(x))); x = x + self.drop_path(self.ls2 * self.mlp(self.norm2(x)))
        return x


class RfdetrViTBackbone(nn.Module):
    def __init__(self, *, img_size=518, patch_size=14, in_chans=3, embed_dim=384, depth=12, num_heads=6, mlp_ratio=4.0, qkv_bias=True, drop_rate=0.0, attn_drop_rate=0.0, drop_path_rate=0.0, layer_scale=1.0, out_feature_indexes=None) -> None:
        super().__init__()
        self.embed_dim = embed_dim; self.patch_size = patch_size; self.out_feature_indexes = out_feature_indexes or [2, 5, 8, 11]
        self.patch_embed = PatchEmbed(img_size=img_size, patch_size=patch_size, in_chans=in_chans, embed_dim=embed_dim)
        num_p = (img_size // patch_size) ** 2
        self.cls_token = nn.Parameter(torch.zeros(1, 1, embed_dim)); self.pos_embed = nn.Parameter(torch.zeros(1, num_p + 1, embed_dim))
        self.pos_drop = nn.Dropout(p=drop_rate)
        dpr = [x.item() for x in torch.linspace(0, drop_path_rate, depth)]
        self.blocks = nn.ModuleList([RfdetrBlock(dim=embed_dim, num_heads=num_heads, mlp_ratio=mlp_ratio, qkv_bias=qkv_bias, drop=drop_rate, attn_drop=attn_drop_rate, drop_path=dpr[i], layer_scale=layer_scale) for i in range(depth)])
        self.norm = nn.LayerNorm(embed_dim, eps=1e-6); self._init_weights()

    def _init_weights(self) -> None:
        nn.init.trunc_normal_(self.pos_embed, std=0.02); nn.init.trunc_normal_(self.cls_token, std=0.02)
        self.apply(_init_vit_weights)

    def _interp_pos(self, x: torch.Tensor, hp: int, wp: int) -> torch.Tensor:
        n = x.shape[1] - 1; N = self.pos_embed.shape[1] - 1
        if n == N and hp == wp: return self.pos_embed
        pe = self.pos_embed[:, 1:].reshape(1, int(math.sqrt(N)), int(math.sqrt(N)), self.embed_dim).permute(0, 3, 1, 2)
        ph, pw = hp // self.patch_size, wp // self.patch_size
        pe = F.interpolate(pe, size=(ph, pw), mode="bicubic", align_corners=False).permute(0, 2, 3, 1).reshape(1, -1, self.embed_dim)
        return torch.cat((self.pos_embed[:, :1], pe), dim=1)

    def forward(self, x: torch.Tensor) -> tuple[list[torch.Tensor], list[torch.Tensor]]:
        B, C, H, W = x.shape
        x = self.patch_embed(x); x = torch.cat((self.cls_token.expand(B, -1, -1), x), dim=1)
        x = self.pos_drop(x + self._interp_pos(x, H, W))
        feats, masks = [], []
        for i, blk in enumerate(self.blocks):
            x = blk(x)
            if i in self.out_feature_indexes:
                fh, fw = H // self.patch_size, W // self.patch_size
                feats.append(self.norm(x[:, 1:]).transpose(1, 2).reshape(B, self.embed_dim, fh, fw))
                masks.append(torch.zeros((B, fh, fw), dtype=torch.bool, device=x.device))
        return feats, masks


def _init_vit_weights(m: nn.Module) -> None:
    if isinstance(m, nn.Linear): nn.init.trunc_normal_(m.weight, std=0.02); m.bias is not None and nn.init.zeros_(m.bias)
    elif isinstance(m, nn.LayerNorm): nn.init.zeros_(m.bias); nn.init.ones_(m.weight)


# -- Projector --

class MultiScaleProjector(nn.Module):
    def __init__(self, in_channels=None, out_channels=256, scale_factors=None) -> None:
        super().__init__()
        in_channels = in_channels or [384] * 4; scale_factors = scale_factors or [2.0, 1.0, 0.5, 0.25]
        self.projections = nn.ModuleList([nn.Conv2d(ic, out_channels, 1) for ic in in_channels]); self.scale_factors = scale_factors

    def forward(self, feats: list[torch.Tensor]) -> list[torch.Tensor]:
        return [F.interpolate(p(f), size=(max(1, int(f.shape[2] * s)), max(1, int(f.shape[3] * s))), mode="bilinear", align_corners=False) if s != 1.0 else p(f) for f, p, s in zip(feats, self.projections, self.scale_factors, strict=True)]


# -- MLP --

class MLP(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int, output_dim: int, num_layers: int) -> None:
        super().__init__(); self.num_layers = num_layers
        d = [input_dim] + [hidden_dim] * (num_layers - 1) + [output_dim]
        self.layers = nn.ModuleList(nn.Linear(d[i], d[i + 1]) for i in range(num_layers))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for i, l in enumerate(self.layers): x = F.relu(l(x)) if i < self.num_layers - 1 else l(x)
        return x


# -- Position encoding --

def gen_sineembed(pos_tensor: torch.Tensor, dim: int = 128) -> torch.Tensor:
    scale = 2.0 * math.pi
    dim_t = torch.arange(dim, dtype=pos_tensor.dtype, device=pos_tensor.device)
    dim_t = 10000 ** (2 * (dim_t // 2) / dim)
    x_embed = pos_tensor[:, :, 0] * scale; y_embed = pos_tensor[:, :, 1] * scale
    px = x_embed[:, :, None] / dim_t; py = y_embed[:, :, None] / dim_t
    px = torch.stack((px[:, :, 0::2].sin(), px[:, :, 1::2].cos()), dim=3).flatten(2)
    py = torch.stack((py[:, :, 0::2].sin(), py[:, :, 1::2].cos()), dim=3).flatten(2)
    if pos_tensor.size(-1) == 4:
        we = pos_tensor[:, :, 2] * scale; he = pos_tensor[:, :, 3] * scale
        pw = we[:, :, None] / dim_t; ph = he[:, :, None] / dim_t
        pw = torch.stack((pw[:, :, 0::2].sin(), pw[:, :, 1::2].cos()), dim=3).flatten(2)
        ph = torch.stack((ph[:, :, 0::2].sin(), ph[:, :, 1::2].cos()), dim=3).flatten(2)
        return torch.cat((py, px, pw, ph), dim=2)
    return torch.cat((py, px), dim=2)


# -- MSDeformAttn (aligned with reference call signature) --

class MSDeformAttn(nn.Module):
    def __init__(self, d_model=256, n_levels=4, n_heads=8, n_points=4) -> None:
        super().__init__()
        self.d_model = d_model; self.n_levels = n_levels; self.n_heads = n_heads; self.n_points = n_points
        self.sampling_offsets = nn.Linear(d_model, n_heads * n_levels * n_points * 2)
        self.attention_weights = nn.Linear(d_model, n_heads * n_levels * n_points)
        self.value_proj = nn.Linear(d_model, d_model); self.output_proj = nn.Linear(d_model, d_model)
        self._reset_parameters()

    def _reset_parameters(self) -> None:
        nn.init.constant_(self.sampling_offsets.weight.data, 0.0); nn.init.constant_(self.sampling_offsets.bias.data, 0.0)
        nn.init.constant_(self.attention_weights.weight.data, 0.0); nn.init.constant_(self.attention_weights.bias.data, 0.0)
        nn.init.xavier_uniform_(self.value_proj.weight.data); nn.init.constant_(self.value_proj.bias.data, 0.0)
        nn.init.xavier_uniform_(self.output_proj.weight.data); nn.init.constant_(self.output_proj.bias.data, 0.0)

    def forward(self, query: torch.Tensor, reference_points: torch.Tensor, value: torch.Tensor, spatial_shapes: torch.Tensor, level_start_index: torch.Tensor, memory_key_padding_mask: torch.Tensor | None = None, input_spatial_shapes_hw: list | None = None) -> torch.Tensor:
        B, N, _ = query.shape; _, L, _ = value.shape
        nh, nl, np_val = self.n_heads, self.n_levels, self.n_points
        value = self.value_proj(value).view(B, L, nh, -1)
        offsets = self.sampling_offsets(query).view(B, N, nh, nl, np_val, 2)
        attn = self.attention_weights(query).view(B, N, nh, nl * np_val)
        attn = F.softmax(attn, dim=-1).view(B, N, nh, nl, np_val)
        if reference_points.shape[-1] == 2:
            rp = reference_points[:, :, None, :, None, :]
        else:
            rp = reference_points[:, :, None, :, None, :2]
        sampling_locs = rp + offsets / torch.stack([spatial_shapes[:, 1], spatial_shapes[:, 0]], dim=1).float()[None, None, None, :, None, :]
        sampling_locs = sampling_locs.reshape(B, N * nh, nl, np_val, 2)
        attn = attn.reshape(B, N * nh, 1, nl, np_val)
        head_dim = self.d_model // nh
        output = torch.zeros(B, N * nh, head_dim, device=value.device, dtype=value.dtype)
        for level in range(nl):
            hs = int(spatial_shapes[level, 0]); ws = int(spatial_shapes[level, 1])
            ls = int(level_start_index[level]); le = ls + hs * ws
            lv = value[:, ls:le].reshape(B, hs, ws, nh, head_dim).permute(0, 3, 4, 1, 2).contiguous()
            g = sampling_locs[:, :, level, :, :] * 2.0 - 1.0
            s = F.grid_sample(lv.flatten(0, 1).float(), g.flatten(0, 1).unsqueeze(2).float(), mode="bilinear", padding_mode="zeros", align_corners=False)
            s = s.reshape(B, nh, head_dim, N, np_val).permute(0, 3, 1, 4, 2).reshape(B, N, nh, np_val, head_dim)
            output += (s * attn[:, :, :, level, :, None]).sum(dim=3)
        return self.output_proj(output.reshape(B, N, nh * head_dim))


# -- Decoder Layer (aligned with reference forward_post) --

class RfdetrDecoderLayer(nn.Module):
    def __init__(self, d_model=256, sa_nhead=8, ca_nhead=8, dim_feedforward=1024, dropout=0.0, group_detr=1, n_levels=4) -> None:
        super().__init__()
        self.self_attn = nn.MultiheadAttention(d_model, sa_nhead, dropout=dropout, batch_first=True)
        self.cross_attn = MSDeformAttn(d_model=d_model, n_levels=n_levels, n_heads=ca_nhead)
        self.linear1 = nn.Linear(d_model, dim_feedforward); self.linear2 = nn.Linear(dim_feedforward, d_model)
        self.norm1 = nn.LayerNorm(d_model); self.norm2 = nn.LayerNorm(d_model); self.norm3 = nn.LayerNorm(d_model)
        self.dropout1 = nn.Dropout(dropout); self.dropout2 = nn.Dropout(dropout); self.dropout3 = nn.Dropout(dropout)
        self.group_detr = group_detr; self.nhead = ca_nhead

    @staticmethod
    def _with_pos_embed(tensor: torch.Tensor, pos: torch.Tensor | None) -> torch.Tensor:
        return tensor if pos is None else tensor + pos

    def forward(self, tgt: torch.Tensor, memory: torch.Tensor, query_pos: torch.Tensor | None, ref_pts: torch.Tensor, ss: torch.Tensor, lsi: torch.Tensor, mem_mask: torch.Tensor | None = None) -> torch.Tensor:
        B, nq, _ = tgt.shape
        # Self-attn (with group_detr splitting during training)
        q = k = self._with_pos_embed(tgt, query_pos); v = tgt
        if self.training and self.group_detr > 1:
            gq = nq // self.group_detr; q = torch.cat(q.split(gq, dim=1), dim=0); k = torch.cat(k.split(gq, dim=1), dim=0); v = torch.cat(v.split(gq, dim=1), dim=0)
        tgt2 = self.self_attn(q, k, v)[0]
        if self.training and self.group_detr > 1:
            tgt2 = torch.cat(tgt2.split(B, dim=0), dim=1)
        tgt = tgt + self.dropout1(tgt2); tgt = self.norm1(tgt)
        # Cross-attn (with query_pos injection)
        tgt2 = self.cross_attn(self._with_pos_embed(tgt, query_pos), ref_pts, memory, ss, lsi, mem_mask)
        tgt = tgt + self.dropout2(tgt2); tgt = self.norm2(tgt)
        tgt2 = self.linear2(self.dropout3(F.relu(self.linear1(tgt))))
        tgt = tgt + self.dropout3(tgt2); tgt = self.norm3(tgt)
        return tgt


# -- Decoder (with ref_point_head, get_reference, refpoints_refine, return_intermediate) --

class RfdetrDecoder(nn.Module):
    def __init__(self, layer: nn.Module, num_layers: int, norm: nn.Module | None = None, return_intermediate: bool = True, d_model: int = 256, lite_refpoint_refine: bool = False, bbox_reparam: bool = True) -> None:
        super().__init__()
        self.layers = nn.ModuleList([copy.deepcopy(layer) for _ in range(num_layers)])
        self.num_layers = num_layers; self.norm = norm; self.return_intermediate = return_intermediate
        self.d_model = d_model; self.lite_refpoint_refine = lite_refpoint_refine; self.bbox_reparam = bbox_reparam
        self.ref_point_head = MLP(2 * d_model, d_model, d_model, 2)

    def _get_reference(self, ref_pts: torch.Tensor, valid_ratios: torch.Tensor | None) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        obj_center = ref_pts[..., :4]
        if valid_ratios is not None:
            ref_input = obj_center[:, :, None] * torch.cat([valid_ratios, valid_ratios], -1)[:, None]
        else:
            ref_input = obj_center[:, :, None]
        qse = gen_sineembed(ref_input[:, :, 0, :], self.d_model // 2)
        qp = self.ref_point_head(qse)
        return obj_center, ref_input, qp, qse

    def _refpoints_refine(self, ref_unsigmoid: torch.Tensor, delta: torch.Tensor) -> torch.Tensor:
        if self.bbox_reparam:
            ncx = delta[..., :2] * ref_unsigmoid[..., 2:] + ref_unsigmoid[..., :2]
            nwh = delta[..., 2:].exp() * ref_unsigmoid[..., 2:]
            return torch.cat([ncx, nwh], dim=-1)
        return ref_unsigmoid + delta

    def forward(self, tgt: torch.Tensor, memory: torch.Tensor, pos: torch.Tensor, ref_pts: torch.Tensor, ss: torch.Tensor, lsi: torch.Tensor, valid_ratios: torch.Tensor | None = None, bbox_embed: nn.Module | None = None) -> tuple[torch.Tensor, list[torch.Tensor], list[torch.Tensor]]:
        intermediate, refpoints_list = [], [ref_pts]
        out = tgt; rp = ref_pts
        for lid, layer in enumerate(self.layers):
            if not self.lite_refpoint_refine:
                _, _, qp, _ = self._get_reference(rp, valid_ratios)
            else:
                _, _, qp, _ = self._get_reference(rp, valid_ratios) if lid == 0 else (None, None, None, None)
                qp = qp if lid == 0 else qp
            out = layer(out, memory, qp, rp, ss, lsi)
            if not self.lite_refpoint_refine and bbox_embed is not None:
                delta = bbox_embed(out)
                new_rp = self._refpoints_refine(rp, delta)
                if lid != self.num_layers - 1:
                    refpoints_list.append(new_rp)
                rp = new_rp.detach()
            if self.return_intermediate:
                intermediate.append(self.norm(out) if self.norm is not None else out)
        if self.norm is not None and self.return_intermediate:
            intermediate[-1] = self.norm(out)
        return out, intermediate, refpoints_list


# -- Detection Head (class_embed with num_classes+1) --

class RfdetrDetectionHead(nn.Module):
    def __init__(self, hidden_dim: int, num_classes: int) -> None:
        super().__init__()
        nc = num_classes + 1  # +1 for "no object" (aligns with reference build_model)
        self.class_embed = nn.Linear(hidden_dim, nc)
        self.bbox_embed = MLP(hidden_dim, hidden_dim, 4, 3)
        prior_prob = 0.01
        self.class_embed.bias.data = torch.ones(nc) * (-math.log((1 - prior_prob) / prior_prob))
        for l in self.bbox_embed.layers:
            if isinstance(l, nn.Linear): nn.init.constant_(l.bias.data, 0.0); nn.init.xavier_uniform_(l.weight.data)
        nn.init.constant_(self.bbox_embed.layers[-1].bias.data, 0.0); nn.init.constant_(self.bbox_embed.layers[-1].weight.data, 0.0)

    def forward(self, hs: torch.Tensor, ref_unsigmoid: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        pred_logits = self.class_embed(hs)
        delta = self.bbox_embed(hs)
        rc, ry = ref_unsigmoid[..., 0:1], ref_unsigmoid[..., 1:2]
        rw = ref_unsigmoid[..., 2:3] if ref_unsigmoid.shape[-1] >= 4 else torch.full_like(rc, 0.05)
        rh = ref_unsigmoid[..., 3:4] if ref_unsigmoid.shape[-1] >= 4 else torch.full_like(rc, 0.05)
        cx = delta[..., 0:1] * rw + rc; cy = delta[..., 1:2] * rh + ry
        w = torch.exp(delta[..., 2:3].clamp(max=4.0)) * rw; h = torch.exp(delta[..., 3:4].clamp(max=4.0)) * rh
        return pred_logits, torch.cat([cx, cy, w, h], dim=-1)


# -- PostProcess (uses num_classes with +1) --

class RfdetrPostProcess(nn.Module):
    def __init__(self, num_select: int = 300) -> None:
        super().__init__(); self.num_select = num_select

    def forward(self, outputs: dict[str, torch.Tensor], target_sizes: torch.Tensor) -> dict[str, torch.Tensor]:
        pl = outputs["pred_logits"]; pb = outputs["pred_boxes"]
        B, Q, nc = pl.shape
        prob = pl.sigmoid()
        scores, labels = prob.max(dim=-1)
        ns = min(self.num_select, Q)
        ts, ti = torch.topk(scores, ns, dim=1)
        bi = torch.arange(B, device=pl.device).unsqueeze(1).expand(-1, ns)
        tl = labels[bi, ti]; tb = pb[bi, ti]
        ih, iw = target_sizes.unbind(1)
        sf = torch.stack([iw, ih, iw, ih], dim=1).unsqueeze(1)
        tbs = tb * sf
        cx, cy, w, h = tbs[..., 0], tbs[..., 1], tbs[..., 2], tbs[..., 3]
        return {"scores": ts, "labels": tl, "boxes_xyxy": torch.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], dim=-1)}


# -- Complete Model --

class RfdetrModel(nn.Module):
    def __init__(self, *, backbone: nn.Module, projector: MultiScaleProjector, hidden_dim=256, num_queries=300, num_decoder_layers=3, sa_nhead=8, ca_nhead=8, num_classes=91, num_select=300, group_detr=1) -> None:
        super().__init__()
        self.backbone = backbone; self.projector = projector
        self.hidden_dim = hidden_dim; self.num_queries = num_queries; self.group_detr = group_detr
        self.query_embed = nn.Embedding(num_queries * group_detr, hidden_dim * 2)
        self.refpoint_embed = nn.Embedding(num_queries * group_detr, 4)
        dl = RfdetrDecoderLayer(d_model=hidden_dim, sa_nhead=sa_nhead, ca_nhead=ca_nhead, group_detr=group_detr, n_levels=len(projector.projections))
        self.decoder = RfdetrDecoder(dl, num_decoder_layers, nn.LayerNorm(hidden_dim), return_intermediate=True, d_model=hidden_dim, bbox_reparam=True)
        self.detection_head = RfdetrDetectionHead(hidden_dim, num_classes)
        self.postprocess = RfdetrPostProcess(num_select=num_select)

    def forward(self, images: torch.Tensor) -> dict[str, Any]:
        feats, masks = self.backbone(images)
        proj = self.projector(feats)
        src, msk, pos_parts, ss_list = [], [], [], []
        for pf, mk in zip(proj, masks):
            B, C, H, W = pf.shape
            src.append(pf.flatten(2).permute(0, 2, 1)); msk.append(mk.flatten(1))
            y, x = torch.meshgrid(torch.arange(H, dtype=torch.float32, device=pf.device), torch.arange(W, dtype=torch.float32, device=pf.device), indexing="ij")
            pos_parts.append(gen_sineembed(torch.stack([x, y], dim=-1).reshape(1, H * W, 2).repeat(B, 1, 1), dim=hidden_dim // 2))
            ss_list.append((H, W))
        memory = torch.cat(src, dim=1); mask_t = torch.cat(msk, dim=1); pos = torch.cat(pos_parts, dim=1)
        ss = torch.tensor(ss_list, device=images.device); lsi = torch.cat((ss.new_zeros((1,)), ss.prod(1).cumsum(0)[:-1]))
        vr = _compute_valid_ratios(msk)
        gd = self.group_detr if self.training else 1
        qf = self.query_embed.weight[:self.num_queries * gd].unsqueeze(0).repeat(B, 1, 1)
        rf = self.refpoint_embed.weight[:self.num_queries * gd].unsqueeze(0).repeat(B, 1, 1).sigmoid()
        tgt = qf[:, :, :self.hidden_dim]
        _, interm, refpoints_list = self.decoder(tgt, memory, pos, rf, ss, lsi, vr, self.detection_head.bbox_embed)
        ref_unsig = refpoints_list[-1] if len(refpoints_list) >= len(interm) else rf
        pred_logits = torch.stack([self.detection_head(h, ref_unsig)[0] for h in interm])
        pred_boxes = torch.stack([self.detection_head(h, ref_unsig)[1] for h in interm])
        return {"pred_logits": pred_logits[-1], "pred_boxes": pred_boxes[-1], "hs": interm, "aux_outputs": [{"pred_logits": pred_logits[i], "pred_boxes": pred_boxes[i]} for i in range(len(interm) - 1)]}


def _compute_valid_ratios(masks: list[torch.Tensor]) -> torch.Tensor:
    vr = []
    for m in masks:
        _, H, W = m.shape
        vr.append(torch.stack([(~m[:, 0, :]).float().sum(dim=1) / W, (~m[:, :, 0]).float().sum(dim=1) / H], dim=-1))
    return torch.stack(vr, dim=1)


_RF_SCALE = {
    "nano": {"hd": 256, "nq": 300, "ndl": 2, "san": 8, "can": 8, "gd": 1, "vd": 12, "ve": 384, "vh": 6, "is": 384, "ps": 14},
    "small": {"hd": 256, "nq": 300, "ndl": 3, "san": 8, "can": 8, "gd": 1, "vd": 12, "ve": 384, "vh": 6, "is": 512, "ps": 14},
    "medium": {"hd": 256, "nq": 300, "ndl": 4, "san": 8, "can": 8, "gd": 1, "vd": 12, "ve": 384, "vh": 6, "is": 576, "ps": 14},
    "large": {"hd": 256, "nq": 300, "ndl": 4, "san": 8, "can": 8, "gd": 1, "vd": 12, "ve": 384, "vh": 6, "is": 704, "ps": 14},
}


def build_rfdetr_model(*, model_scale: str = "nano", num_classes: int = 91, pretrained_path: str | None = None) -> RfdetrModel:
    cfg = _RF_SCALE.get(model_scale)
    if not cfg: raise ServiceConfigurationError(f"RF-DETR 不支持 model_scale={model_scale}")
    bb = RfdetrViTBackbone(img_size=cfg["is"], patch_size=cfg["ps"], embed_dim=cfg["ve"], depth=cfg["vd"], num_heads=cfg["vh"], out_feature_indexes=[2, 5, 8, 11])
    proj = MultiScaleProjector(in_channels=[cfg["ve"]] * 4, out_channels=cfg["hd"], scale_factors=[2.0, 1.0, 0.5, 0.25])
    m = RfdetrModel(backbone=bb, projector=proj, hidden_dim=cfg["hd"], num_queries=cfg["nq"], num_decoder_layers=cfg["ndl"], sa_nhead=cfg["san"], ca_nhead=cfg["can"], num_classes=num_classes, group_detr=cfg["gd"])
    if pretrained_path:
        load_rfdetr_pretrained(m, pretrained_path)
    return m


def load_rfdetr_pretrained(model: RfdetrModel, path: str) -> None:
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    sd = ckpt.get("model", ckpt.get("state_dict", ckpt))
    filtered = {}; ms = model.state_dict()
    for k, v in sd.items():
        ck = k.replace("model.", "").replace("module.", "")
        if ck in ms and ms[ck].shape == v.shape: filtered[ck] = v
    model.load_state_dict(filtered, strict=False)


def _box_cxcywh_to_xyxy(boxes: torch.Tensor) -> torch.Tensor:
    cx, cy, w, h = boxes.unbind(-1)
    return torch.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], dim=-1)


def sigmoid_focal_loss(inputs: torch.Tensor, targets: torch.Tensor, alpha: float = 0.25, gamma: float = 2.0) -> torch.Tensor:
    prob = inputs.sigmoid()
    ce = F.binary_cross_entropy_with_logits(inputs, targets, reduction="none")
    p_t = prob * targets + (1 - prob) * (1 - targets)
    loss = ce * ((1 - p_t) ** gamma)
    if alpha >= 0: loss = (alpha * targets + (1 - alpha) * (1 - targets)) * loss
    return loss.sum() / max(1, int(targets.sum()))
