"""SAM3.1 Multiplex memory attention transformer。"""

from __future__ import annotations

import copy
import math

import torch
from torch import nn
import torch.nn.functional as F

from .vision_backbone import apply_rotary_enc, compute_axial_cis


class Sam3SimpleRoPEAttention(nn.Module):
    """不含 q/k/v projection 的二维 RoPE attention。"""

    def __init__(
        self,
        *,
        model_dim: int = 256,
        head_count: int = 8,
        dropout: float = 0.1,
        rope_theta: float = 10000.0,
        repeat_key_rope: bool = False,
    ) -> None:
        super().__init__()
        if model_dim % head_count != 0:
            raise ValueError("model_dim 必须能整除 head_count")
        self.model_dim = model_dim
        self.head_count = head_count
        self.dropout = dropout
        self.rope_theta = rope_theta
        self.repeat_key_rope = repeat_key_rope
        # complex RoPE 频率不能注册为普通 buffer：owner.to(fp16)
        # 会丢弃其虚部。这里使用显式设备 cache，并在 owner close 时释放。
        self._initial_freqs = compute_axial_cis(
            dim=model_dim // head_count,
            end_x=72,
            end_y=72,
            theta=rope_theta,
        )

    def _resolve_freqs(
        self,
        *,
        token_count: int,
        device: torch.device,
    ) -> torch.Tensor:
        side = math.isqrt(token_count)
        if side * side != token_count:
            raise ValueError(
                "SAM3 memory attention 的 image token 必须构成正方形"
            )
        if self._initial_freqs.shape[0] == token_count:
            if self._initial_freqs.device != device:
                self._initial_freqs = self._initial_freqs.to(device)
            return self._initial_freqs
        return compute_axial_cis(
            dim=self.model_dim // self.head_count,
            end_x=side,
            end_y=side,
            theta=self.rope_theta,
        ).to(device)

    def release_rotary_device_cache(self) -> None:
        """把非 Parameter 的 complex RoPE cache 迁回 CPU。"""

        if self._initial_freqs.device.type != "cpu":
            self._initial_freqs = self._initial_freqs.cpu()

    def forward(
        self,
        query: torch.Tensor,
        key: torch.Tensor,
        value: torch.Tensor,
        *,
        key_tokens_without_rope: int = 0,
    ) -> torch.Tensor:
        """执行 batch-first 多头 attention。"""

        batch_size, query_count, channels = query.shape
        key_count = key.shape[1]
        head_dim = channels // self.head_count
        query_heads = query.reshape(
            batch_size,
            query_count,
            self.head_count,
            head_dim,
        ).transpose(1, 2)
        key_heads = key.reshape(
            batch_size,
            key_count,
            self.head_count,
            head_dim,
        ).transpose(1, 2)
        value_heads = value.reshape(
            value.shape[0],
            key_count,
            self.head_count,
            head_dim,
        ).transpose(1, 2)
        rope_key_count = key_count - key_tokens_without_rope
        frequencies = self._resolve_freqs(
            token_count=query_count,
            device=query.device,
        )
        rotated_query, rotated_key = apply_rotary_enc(
            query_heads,
            key_heads[:, :, :rope_key_count],
            frequencies,
            repeat_freqs_k=self.repeat_key_rope,
        )
        if key_tokens_without_rope:
            rotated_key = torch.cat(
                (
                    rotated_key,
                    key_heads[:, :, rope_key_count:],
                ),
                dim=2,
            )
        output = F.scaled_dot_product_attention(
            rotated_query,
            rotated_key,
            value_heads,
            dropout_p=self.dropout if self.training else 0.0,
        )
        return output.transpose(1, 2).reshape(
            batch_size,
            query_count,
            channels,
        )


class Sam3MultiplexMemoryLayer(nn.Module):
    """SAM3.1 decoupled memory attention 单层。"""

    def __init__(
        self,
        *,
        model_dim: int = 256,
        head_count: int = 8,
        feedforward_dim: int = 2048,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.self_attn_q_proj = nn.Linear(model_dim, model_dim)
        self.self_attn_k_proj = nn.Linear(model_dim, model_dim)
        self.self_attn_v_proj = nn.Linear(model_dim, model_dim)
        self.self_attn_out_proj = nn.Linear(model_dim, model_dim)
        self.cross_attn_q_proj = nn.Linear(model_dim, model_dim)
        self.cross_attn_k_proj = nn.Linear(model_dim, model_dim)
        self.cross_attn_v_proj = nn.Linear(model_dim, model_dim)
        self.cross_attn_out_proj = nn.Linear(model_dim, model_dim)
        self.image_cross_attn_q_proj = nn.Linear(model_dim, model_dim)
        self.image_cross_attn_k_proj = nn.Linear(model_dim, model_dim)
        self.self_attention_rope = Sam3SimpleRoPEAttention(
            model_dim=model_dim,
            head_count=head_count,
            dropout=dropout,
        )
        self.cross_attention_rope = Sam3SimpleRoPEAttention(
            model_dim=model_dim,
            head_count=head_count,
            dropout=dropout,
            repeat_key_rope=True,
        )
        self.linear1 = nn.Linear(model_dim, feedforward_dim)
        self.linear2 = nn.Linear(feedforward_dim, model_dim)
        self.norm1 = nn.LayerNorm(model_dim)
        self.norm2 = nn.LayerNorm(model_dim)
        self.norm3 = nn.LayerNorm(model_dim)
        self.dropout = nn.Dropout(dropout)
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)
        self.dropout3 = nn.Dropout(dropout)

    def forward(
        self,
        *,
        image: torch.Tensor,
        target: torch.Tensor,
        memory_image: torch.Tensor,
        memory: torch.Tensor,
        target_position: torch.Tensor,
        memory_image_position: torch.Tensor,
        object_pointer_token_count: int,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """执行 self-attention、memory cross-attention 与 FFN。"""

        normalized_target = self.norm1(target)
        self_query = self.self_attn_q_proj(normalized_target)
        self_key = self.self_attn_k_proj(normalized_target)
        self_value = self.self_attn_v_proj(normalized_target)
        target = target + self.dropout1(
            self.self_attn_out_proj(
                self.self_attention_rope(
                    self_query,
                    self_key,
                    self_value,
                )
            )
        )

        normalized_target = self.norm2(target)
        cross_query = (
            self.image_cross_attn_q_proj(image)
            + self.cross_attn_q_proj(normalized_target)
        )
        cross_key = (
            self.image_cross_attn_k_proj(memory_image)
            + self.cross_attn_k_proj(memory)
            + memory_image_position
        )
        cross_value = self.cross_attn_v_proj(memory)
        target = target + self.dropout2(
            self.cross_attn_out_proj(
                self.cross_attention_rope(
                    cross_query,
                    cross_key,
                    cross_value,
                    key_tokens_without_rope=object_pointer_token_count,
                )
            )
        )
        normalized_target = self.norm3(target)
        feedforward = self.linear2(
            self.dropout(F.gelu(self.linear1(normalized_target)))
        )
        return image, target + self.dropout3(feedforward)


class Sam3MultiplexMemoryTransformer(nn.Module):
    """融合当前图像、历史 mask memory 和 object pointers。"""

    def __init__(
        self,
        *,
        layer_count: int = 4,
        model_dim: int = 256,
    ) -> None:
        super().__init__()
        layer = Sam3MultiplexMemoryLayer(model_dim=model_dim)
        self.layers = nn.ModuleList(
            copy.deepcopy(layer) for _ in range(layer_count)
        )
        self.norm = nn.LayerNorm(model_dim)

    def forward(
        self,
        *,
        image: torch.Tensor,
        source: torch.Tensor,
        memory_image: torch.Tensor,
        memory: torch.Tensor,
        source_position: torch.Tensor,
        memory_image_position: torch.Tensor,
        memory_position: torch.Tensor,
        object_pointer_token_count: int = 0,
    ) -> dict[str, torch.Tensor]:
        """按 batch-first layout 返回 memory-conditioned image feature。"""

        output = source + 0.1 * source_position
        if memory_image.shape[1] != memory.shape[1]:
            difference = memory.shape[1] - memory_image.shape[1]
            if difference != object_pointer_token_count:
                raise ValueError(
                    "SAM3 memory image 与 object pointer token 数量不一致"
                )
            memory_image = torch.cat(
                (
                    memory_image,
                    memory_image.new_zeros(
                        memory_image.shape[0],
                        difference,
                        memory_image.shape[2],
                    ),
                ),
                dim=1,
            )
            memory_image_position = torch.cat(
                (
                    memory_image_position,
                    memory_position[:1, -difference:],
                ),
                dim=1,
            )
        for layer in self.layers:
            image, output = layer(
                image=image,
                target=output,
                memory_image=memory_image,
                memory=memory,
                target_position=source_position,
                memory_image_position=memory_image_position,
                object_pointer_token_count=object_pointer_token_count,
            )
        return {
            "memory": self.norm(output),
            "pos_embed": source_position,
        }


__all__ = ["Sam3MultiplexMemoryTransformer"]
