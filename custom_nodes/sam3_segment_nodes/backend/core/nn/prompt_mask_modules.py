"""SAM3 单图 interactive 所需的 prompt/mask 模块。"""

from __future__ import annotations

import math

import torch
from torch import nn

from .common import LayerNorm2d, MLP, MLPBlock


class PositionEmbeddingRandom(nn.Module):
    """基于随机频率的二维位置编码。"""

    def __init__(self, num_pos_feats: int = 64, scale: float | None = None) -> None:
        super().__init__()
        if scale is None or scale <= 0.0:
            scale = 1.0
        self.register_buffer("positional_encoding_gaussian_matrix", scale * torch.randn((2, num_pos_feats)))

    def _pe_encoding(self, coords: torch.Tensor) -> torch.Tensor:
        coords = coords.to(
            device=self.positional_encoding_gaussian_matrix.device,
            dtype=self.positional_encoding_gaussian_matrix.dtype,
        )
        coords = 2.0 * coords - 1.0
        coords = coords @ self.positional_encoding_gaussian_matrix
        coords = 2.0 * math.pi * coords
        return torch.cat([torch.sin(coords), torch.cos(coords)], dim=-1)

    def forward(self, size: tuple[int, int]) -> torch.Tensor:
        height, width = size
        grid = torch.ones(
            (height, width),
            device=self.positional_encoding_gaussian_matrix.device,
            dtype=self.positional_encoding_gaussian_matrix.dtype,
        )
        y_embed = grid.cumsum(dim=0) - 0.5
        x_embed = grid.cumsum(dim=1) - 0.5
        y_embed = y_embed / height
        x_embed = x_embed / width
        pe = self._pe_encoding(torch.stack([x_embed, y_embed], dim=-1))
        return pe.permute(2, 0, 1)

    def forward_with_coords(self, coords_input: torch.Tensor, image_size: tuple[int, int]) -> torch.Tensor:
        coords = coords_input.clone()
        coords[:, :, 0] = coords[:, :, 0] / image_size[1]
        coords[:, :, 1] = coords[:, :, 1] / image_size[0]
        return self._pe_encoding(coords)


class PromptEncoder(nn.Module):
    """把 point/box/mask prompt 编成 SAM 头可消费的 embedding。"""

    def __init__(
        self,
        embed_dim: int,
        image_embedding_size: tuple[int, int],
        input_image_size: tuple[int, int],
        mask_in_chans: int,
        activation: type[nn.Module] = nn.GELU,
    ) -> None:
        super().__init__()
        self.embed_dim = embed_dim
        self.input_image_size = input_image_size
        self.image_embedding_size = image_embedding_size
        self.pe_layer = PositionEmbeddingRandom(embed_dim // 2)

        self.num_point_embeddings = 4
        self.point_embeddings = nn.ModuleList(nn.Embedding(1, embed_dim) for _ in range(self.num_point_embeddings))
        self.not_a_point_embed = nn.Embedding(1, embed_dim)

        self.mask_input_size = (4 * image_embedding_size[0], 4 * image_embedding_size[1])
        self.mask_downscaling = nn.Sequential(
            nn.Conv2d(1, mask_in_chans // 4, kernel_size=2, stride=2),
            LayerNorm2d(mask_in_chans // 4),
            activation(),
            nn.Conv2d(mask_in_chans // 4, mask_in_chans, kernel_size=2, stride=2),
            LayerNorm2d(mask_in_chans),
            activation(),
            nn.Conv2d(mask_in_chans, embed_dim, kernel_size=1),
        )
        self.no_mask_embed = nn.Embedding(1, embed_dim)

    def get_dense_pe(self) -> torch.Tensor:
        return self.pe_layer(self.image_embedding_size).unsqueeze(0)

    def _embed_points(self, points: torch.Tensor, labels: torch.Tensor, pad: bool) -> torch.Tensor:
        points = points + 0.5
        if pad:
            padding_point = torch.zeros((points.shape[0], 1, 2), dtype=points.dtype, device=points.device)
            padding_label = -torch.ones((labels.shape[0], 1), dtype=labels.dtype, device=labels.device)
            points = torch.cat([points, padding_point], dim=1)
            labels = torch.cat([labels, padding_label], dim=1)
        point_embedding = self.pe_layer.forward_with_coords(points, self.input_image_size)
        point_embedding[labels == -1] = 0.0
        point_embedding[labels == -1] += self.not_a_point_embed.weight
        point_embedding[labels == 0] += self.point_embeddings[0].weight
        point_embedding[labels == 1] += self.point_embeddings[1].weight
        point_embedding[labels == 2] += self.point_embeddings[2].weight
        point_embedding[labels == 3] += self.point_embeddings[3].weight
        return point_embedding

    def _embed_boxes(self, boxes: torch.Tensor) -> torch.Tensor:
        boxes = boxes + 0.5
        coords = boxes.reshape(-1, 2, 2)
        corner_embedding = self.pe_layer.forward_with_coords(coords, self.input_image_size)
        corner_embedding[:, 0, :] += self.point_embeddings[2].weight
        corner_embedding[:, 1, :] += self.point_embeddings[3].weight
        return corner_embedding

    def _embed_masks(self, masks: torch.Tensor) -> torch.Tensor:
        return self.mask_downscaling(masks)

    @staticmethod
    def _get_batch_size(
        points: tuple[torch.Tensor, torch.Tensor] | None,
        boxes: torch.Tensor | None,
        masks: torch.Tensor | None,
    ) -> int:
        if points is not None:
            return points[0].shape[0]
        if boxes is not None:
            return boxes.shape[0]
        if masks is not None:
            return masks.shape[0]
        return 1

    def forward(
        self,
        points: tuple[torch.Tensor, torch.Tensor] | None,
        boxes: torch.Tensor | None,
        masks: torch.Tensor | None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        batch_size = self._get_batch_size(points, boxes, masks)
        sparse_embeddings = torch.empty(
            (batch_size, 0, self.embed_dim),
            dtype=self.point_embeddings[0].weight.dtype,
            device=self.point_embeddings[0].weight.device,
        )
        if points is not None:
            coords, labels = points
            point_embeddings = self._embed_points(coords, labels, pad=(boxes is None))
            sparse_embeddings = torch.cat([sparse_embeddings, point_embeddings], dim=1)
        if boxes is not None:
            box_embeddings = self._embed_boxes(boxes)
            sparse_embeddings = torch.cat([sparse_embeddings, box_embeddings], dim=1)

        if masks is not None:
            dense_embeddings = self._embed_masks(masks)
        else:
            dense_embeddings = self.no_mask_embed.weight.reshape(1, -1, 1, 1).expand(
                batch_size,
                -1,
                self.image_embedding_size[0],
                self.image_embedding_size[1],
            )
        return sparse_embeddings, dense_embeddings


class Attention(nn.Module):
    """SAM two-way transformer 使用的 attention。"""

    def __init__(
        self,
        embedding_dim: int,
        num_heads: int,
        downsample_rate: int = 1,
        kv_in_dim: int | None = None,
    ) -> None:
        super().__init__()
        self.embedding_dim = embedding_dim
        self.kv_in_dim = kv_in_dim if kv_in_dim is not None else embedding_dim
        self.internal_dim = embedding_dim // downsample_rate
        self.num_heads = num_heads
        if self.internal_dim % num_heads != 0:
            raise ValueError("Attention 内部维度必须能整除 num_heads")

        self.q_proj = nn.Linear(embedding_dim, self.internal_dim)
        self.k_proj = nn.Linear(self.kv_in_dim, self.internal_dim)
        self.v_proj = nn.Linear(self.kv_in_dim, self.internal_dim)
        self.out_proj = nn.Linear(self.internal_dim, embedding_dim)

    @staticmethod
    def _separate_heads(x: torch.Tensor, num_heads: int) -> torch.Tensor:
        batch_size, token_count, channels = x.shape
        x = x.reshape(batch_size, token_count, num_heads, channels // num_heads)
        return x.transpose(1, 2)

    @staticmethod
    def _recombine_heads(x: torch.Tensor) -> torch.Tensor:
        batch_size, num_heads, token_count, channels = x.shape
        x = x.transpose(1, 2)
        return x.reshape(batch_size, token_count, num_heads * channels)

    def forward(self, q: torch.Tensor, k: torch.Tensor, v: torch.Tensor) -> torch.Tensor:
        q = self.q_proj(q)
        k = self.k_proj(k)
        v = self.v_proj(v)

        q = self._separate_heads(q, self.num_heads)
        k = self._separate_heads(k, self.num_heads)
        v = self._separate_heads(v, self.num_heads)

        _, _, _, channels_per_head = q.shape
        attention_scores = q @ k.permute(0, 1, 3, 2)
        attention_scores = attention_scores / math.sqrt(channels_per_head)
        attention_scores = torch.softmax(attention_scores, dim=-1)

        out = attention_scores @ v
        out = self._recombine_heads(out)
        return self.out_proj(out)


class TwoWayAttentionBlock(nn.Module):
    """SAM 两路注意力 block。"""

    def __init__(
        self,
        embedding_dim: int,
        num_heads: int,
        mlp_dim: int = 2048,
        activation: type[nn.Module] = nn.ReLU,
        attention_downsample_rate: int = 2,
        skip_first_layer_pe: bool = False,
    ) -> None:
        super().__init__()
        self.self_attn = Attention(embedding_dim, num_heads)
        self.norm1 = nn.LayerNorm(embedding_dim)

        self.cross_attn_token_to_image = Attention(embedding_dim, num_heads, downsample_rate=attention_downsample_rate)
        self.norm2 = nn.LayerNorm(embedding_dim)

        self.mlp = MLPBlock(embedding_dim, mlp_dim, activation)
        self.norm3 = nn.LayerNorm(embedding_dim)

        self.norm4 = nn.LayerNorm(embedding_dim)
        self.cross_attn_image_to_token = Attention(embedding_dim, num_heads, downsample_rate=attention_downsample_rate)
        self.skip_first_layer_pe = bool(skip_first_layer_pe)

    def forward(
        self,
        queries: torch.Tensor,
        keys: torch.Tensor,
        query_pe: torch.Tensor,
        key_pe: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if self.skip_first_layer_pe:
            queries = self.self_attn(q=queries, k=queries, v=queries)
        else:
            q = queries + query_pe
            attention_out = self.self_attn(q=q, k=q, v=queries)
            queries = queries + attention_out
        queries = self.norm1(queries)

        q = queries + query_pe
        k = keys + key_pe
        attention_out = self.cross_attn_token_to_image(q=q, k=k, v=keys)
        queries = queries + attention_out
        queries = self.norm2(queries)

        mlp_out = self.mlp(queries)
        queries = queries + mlp_out
        queries = self.norm3(queries)

        q = queries + query_pe
        k = keys + key_pe
        attention_out = self.cross_attn_image_to_token(q=k, k=q, v=queries)
        keys = keys + attention_out
        keys = self.norm4(keys)
        return queries, keys


class TwoWayTransformer(nn.Module):
    """SAM 的基础 two-way transformer。"""

    def __init__(
        self,
        depth: int,
        embedding_dim: int,
        num_heads: int,
        mlp_dim: int,
        activation: type[nn.Module] = nn.ReLU,
        attention_downsample_rate: int = 2,
    ) -> None:
        super().__init__()
        self.depth = depth
        self.embedding_dim = embedding_dim
        self.num_heads = num_heads
        self.mlp_dim = mlp_dim
        self.layers = nn.ModuleList(
            TwoWayAttentionBlock(
                embedding_dim=embedding_dim,
                num_heads=num_heads,
                mlp_dim=mlp_dim,
                activation=activation,
                attention_downsample_rate=attention_downsample_rate,
                skip_first_layer_pe=(index == 0),
            )
            for index in range(depth)
        )
        self.final_attn_token_to_image = Attention(
            embedding_dim,
            num_heads,
            downsample_rate=attention_downsample_rate,
        )
        self.norm_final_attn = nn.LayerNorm(embedding_dim)

    def forward(
        self,
        image_embedding: torch.Tensor,
        image_pe: torch.Tensor,
        point_embedding: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        image_embedding = image_embedding.flatten(2).permute(0, 2, 1)
        image_pe = image_pe.flatten(2).permute(0, 2, 1)

        queries = point_embedding
        keys = image_embedding
        for layer in self.layers:
            queries, keys = layer(
                queries=queries,
                keys=keys,
                query_pe=point_embedding,
                key_pe=image_pe,
            )
        q = queries + point_embedding
        k = keys + image_pe
        attention_out = self.final_attn_token_to_image(q=q, k=k, v=keys)
        queries = self.norm_final_attn(queries + attention_out)
        return queries, keys


class SAM2TwoWayAttentionBlock(TwoWayAttentionBlock):
    """SAM2 兼容版 attention block。"""

    def __init__(
        self,
        embedding_dim: int,
        num_heads: int,
        mlp_dim: int = 2048,
        activation: type[nn.Module] = nn.ReLU,
        attention_downsample_rate: int = 2,
        skip_first_layer_pe: bool = False,
    ) -> None:
        super().__init__(
            embedding_dim=embedding_dim,
            num_heads=num_heads,
            mlp_dim=mlp_dim,
            activation=activation,
            attention_downsample_rate=attention_downsample_rate,
            skip_first_layer_pe=skip_first_layer_pe,
        )
        self.mlp = MLP(embedding_dim, mlp_dim, embedding_dim, num_layers=2, act=activation)


class SAM2TwoWayTransformer(TwoWayTransformer):
    """SAM2 兼容版 two-way transformer。"""

    def __init__(
        self,
        depth: int,
        embedding_dim: int,
        num_heads: int,
        mlp_dim: int,
        activation: type[nn.Module] = nn.ReLU,
        attention_downsample_rate: int = 2,
    ) -> None:
        super().__init__(
            depth=depth,
            embedding_dim=embedding_dim,
            num_heads=num_heads,
            mlp_dim=mlp_dim,
            activation=activation,
            attention_downsample_rate=attention_downsample_rate,
        )
        self.layers = nn.ModuleList(
            SAM2TwoWayAttentionBlock(
                embedding_dim=embedding_dim,
                num_heads=num_heads,
                mlp_dim=mlp_dim,
                activation=activation,
                attention_downsample_rate=attention_downsample_rate,
                skip_first_layer_pe=(index == 0),
            )
            for index in range(depth)
        )


class SAM2MaskDecoder(nn.Module):
    """SAM2 风格 mask decoder。"""

    def __init__(
        self,
        transformer_dim: int,
        transformer: nn.Module,
        num_multimask_outputs: int = 3,
        activation: type[nn.Module] = nn.GELU,
        iou_head_depth: int = 3,
        iou_head_hidden_dim: int = 256,
        use_high_res_features: bool = False,
        iou_prediction_use_sigmoid: bool = False,
        dynamic_multimask_via_stability: bool = False,
        dynamic_multimask_stability_delta: float = 0.05,
        dynamic_multimask_stability_thresh: float = 0.98,
        pred_obj_scores: bool = False,
        pred_obj_scores_mlp: bool = False,
        use_multimask_token_for_obj_ptr: bool = False,
    ) -> None:
        super().__init__()
        self.transformer_dim = transformer_dim
        self.transformer = transformer
        self.num_multimask_outputs = num_multimask_outputs

        self.iou_token = nn.Embedding(1, transformer_dim)
        self.num_mask_tokens = num_multimask_outputs + 1
        self.mask_tokens = nn.Embedding(self.num_mask_tokens, transformer_dim)

        self.pred_obj_scores = bool(pred_obj_scores)
        if self.pred_obj_scores:
            self.obj_score_token = nn.Embedding(1, transformer_dim)
        self.use_multimask_token_for_obj_ptr = bool(use_multimask_token_for_obj_ptr)

        self.output_upscaling = nn.Sequential(
            nn.ConvTranspose2d(transformer_dim, transformer_dim // 4, kernel_size=2, stride=2),
            LayerNorm2d(transformer_dim // 4),
            activation(),
            nn.ConvTranspose2d(transformer_dim // 4, transformer_dim // 8, kernel_size=2, stride=2),
            activation(),
        )
        self.use_high_res_features = bool(use_high_res_features)
        if self.use_high_res_features:
            self.conv_s0 = nn.Conv2d(transformer_dim, transformer_dim // 8, kernel_size=1, stride=1)
            self.conv_s1 = nn.Conv2d(transformer_dim, transformer_dim // 4, kernel_size=1, stride=1)

        self.output_hypernetworks_mlps = nn.ModuleList(
            MLP(transformer_dim, transformer_dim, transformer_dim // 8, 3) for _ in range(self.num_mask_tokens)
        )
        self.iou_prediction_head = MLP(
            transformer_dim,
            iou_head_hidden_dim,
            self.num_mask_tokens,
            iou_head_depth,
            sigmoid=iou_prediction_use_sigmoid,
        )
        if self.pred_obj_scores:
            self.pred_obj_score_head = nn.Linear(transformer_dim, 1)
            if pred_obj_scores_mlp:
                self.pred_obj_score_head = MLP(transformer_dim, transformer_dim, 1, 3)

        self.dynamic_multimask_via_stability = bool(dynamic_multimask_via_stability)
        self.dynamic_multimask_stability_delta = float(dynamic_multimask_stability_delta)
        self.dynamic_multimask_stability_thresh = float(dynamic_multimask_stability_thresh)

    def forward(
        self,
        image_embeddings: torch.Tensor,
        image_pe: torch.Tensor,
        sparse_prompt_embeddings: torch.Tensor,
        dense_prompt_embeddings: torch.Tensor,
        multimask_output: bool,
        repeat_image: bool,
        high_res_features: list[torch.Tensor] | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        masks, iou_pred, mask_tokens_out, object_score_logits = self.predict_masks(
            image_embeddings=image_embeddings,
            image_pe=image_pe,
            sparse_prompt_embeddings=sparse_prompt_embeddings,
            dense_prompt_embeddings=dense_prompt_embeddings,
            repeat_image=repeat_image,
            high_res_features=high_res_features,
        )

        if multimask_output:
            masks = masks[:, 1:, :, :]
            iou_pred = iou_pred[:, 1:]
        elif self.dynamic_multimask_via_stability and not self.training:
            masks, iou_pred = self._dynamic_multimask_via_stability(masks, iou_pred)
        else:
            masks = masks[:, 0:1, :, :]
            iou_pred = iou_pred[:, 0:1]

        if multimask_output and self.use_multimask_token_for_obj_ptr:
            sam_tokens_out = mask_tokens_out[:, 1:]
        else:
            sam_tokens_out = mask_tokens_out[:, 0:1]
        return masks, iou_pred, sam_tokens_out, object_score_logits

    def predict_masks(
        self,
        image_embeddings: torch.Tensor,
        image_pe: torch.Tensor,
        sparse_prompt_embeddings: torch.Tensor,
        dense_prompt_embeddings: torch.Tensor,
        repeat_image: bool,
        high_res_features: list[torch.Tensor] | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        extra_token_count = 0
        if self.pred_obj_scores:
            output_tokens = torch.cat(
                [self.obj_score_token.weight, self.iou_token.weight, self.mask_tokens.weight],
                dim=0,
            )
            extra_token_count = 1
        else:
            output_tokens = torch.cat([self.iou_token.weight, self.mask_tokens.weight], dim=0)
        output_tokens = output_tokens.unsqueeze(0).expand(sparse_prompt_embeddings.shape[0], -1, -1)
        tokens = torch.cat((output_tokens, sparse_prompt_embeddings), dim=1)

        if repeat_image:
            src = torch.repeat_interleave(image_embeddings, tokens.shape[0], dim=0)
        else:
            if image_embeddings.shape[0] != tokens.shape[0]:
                raise ValueError("repeat_image=False 时 image_embeddings batch 必须与 tokens 一致")
            src = image_embeddings
        src = src + dense_prompt_embeddings
        if image_pe.shape[0] != 1:
            raise ValueError("SAM2MaskDecoder 要求 image_pe 的 batch 维固定为 1")
        pos_src = torch.repeat_interleave(image_pe, tokens.shape[0], dim=0)
        batch_size, channels, height, width = src.shape

        hidden_states, src = self.transformer(src, pos_src, tokens)
        iou_token_out = hidden_states[:, extra_token_count, :]
        mask_tokens_out = hidden_states[:, extra_token_count + 1 : (extra_token_count + 1 + self.num_mask_tokens), :]

        src = src.transpose(1, 2).view(batch_size, channels, height, width)
        if not self.use_high_res_features or high_res_features is None:
            upscaled_embedding = self.output_upscaling(src)
        else:
            deconv1, layer_norm1, activation1, deconv2, activation2 = self.output_upscaling
            feat_s0, feat_s1 = high_res_features
            upscaled_embedding = activation1(layer_norm1(deconv1(src) + feat_s1))
            upscaled_embedding = activation2(deconv2(upscaled_embedding) + feat_s0)

        hyper_inputs = torch.stack(
            [self.output_hypernetworks_mlps[index](mask_tokens_out[:, index, :]) for index in range(self.num_mask_tokens)],
            dim=1,
        )
        batch_size, channels, height, width = upscaled_embedding.shape
        masks = (hyper_inputs @ upscaled_embedding.view(batch_size, channels, height * width)).view(
            batch_size,
            -1,
            height,
            width,
        )

        iou_pred = self.iou_prediction_head(iou_token_out)
        if self.pred_obj_scores:
            object_score_logits = self.pred_obj_score_head(hidden_states[:, 0, :])
        else:
            object_score_logits = 10.0 * iou_pred.new_ones(iou_pred.shape[0], 1)
        return masks, iou_pred, mask_tokens_out, object_score_logits

    def _get_stability_scores(self, mask_logits: torch.Tensor) -> torch.Tensor:
        mask_logits = mask_logits.flatten(-2)
        area_intersection = torch.sum(mask_logits > self.dynamic_multimask_stability_delta, dim=-1).float()
        area_union = torch.sum(mask_logits > -self.dynamic_multimask_stability_delta, dim=-1).float()
        return torch.where(area_union > 0, area_intersection / area_union, 1.0)

    def _dynamic_multimask_via_stability(
        self,
        all_mask_logits: torch.Tensor,
        all_iou_scores: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        multimask_logits = all_mask_logits[:, 1:, :, :]
        multimask_iou_scores = all_iou_scores[:, 1:]
        best_indices = torch.argmax(multimask_iou_scores, dim=-1)
        batch_indices = torch.arange(multimask_iou_scores.shape[0], device=all_iou_scores.device)
        best_multimask_logits = multimask_logits[batch_indices, best_indices].unsqueeze(1)
        best_multimask_iou_scores = multimask_iou_scores[batch_indices, best_indices].unsqueeze(1)

        singlemask_logits = all_mask_logits[:, 0:1, :, :]
        singlemask_iou_scores = all_iou_scores[:, 0:1]
        stability_scores = self._get_stability_scores(singlemask_logits)
        is_stable = stability_scores >= self.dynamic_multimask_stability_thresh

        mask_logits_out = torch.where(
            is_stable[..., None, None].expand_as(singlemask_logits),
            singlemask_logits,
            best_multimask_logits,
        )
        iou_scores_out = torch.where(
            is_stable.expand_as(singlemask_iou_scores),
            singlemask_iou_scores,
            best_multimask_iou_scores,
        )
        return mask_logits_out, iou_scores_out


__all__ = [
    "Attention",
    "PositionEmbeddingRandom",
    "PromptEncoder",
    "SAM2MaskDecoder",
    "SAM2TwoWayTransformer",
    "TwoWayTransformer",
]
