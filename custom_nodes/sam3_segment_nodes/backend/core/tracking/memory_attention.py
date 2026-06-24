"""SAM3 视频 interactive 的 memory-attention 跟踪 helper。"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn.functional as F

from ..models.interactive import Sam3InteractiveFrameContext
from ..postprocess.masks import Sam3RegionItem
from .common import (
    build_fused_history_mask_from_tensors,
    decode_mask_png,
    extract_feature_prototype,
    keep_largest_component,
    resize_binary_mask,
    resolve_target_pixel_count,
    upsample_binary_mask,
)


@dataclass(frozen=True)
class Sam3VideoAttentionMemoryEntry:
    """描述一帧对象记忆条目。"""

    object_tokens: torch.Tensor
    low_res_mask: torch.Tensor
    score: float
    frame_index: int


@dataclass
class Sam3VideoAttentionTrackState:
    """描述一个视频对象的 attention 记忆状态。"""

    prompt_id: str
    display_name: str
    memory_entries: list[Sam3VideoAttentionMemoryEntry] = field(default_factory=list)
    feature_prototype: torch.Tensor | None = None
    last_score: float = 0.0
    last_frame_index: int | None = None


@dataclass(frozen=True)
class Sam3MemoryAttentionPromptBuildResult:
    """描述一次 memory attention prompt 构造结果。"""

    prompt_mask: np.ndarray
    history_length: int
    attention_peak: float
    prototype_ready: bool
    memory_entry_count: int


def build_memory_attention_prompt_mask(
    *,
    frame_context: Sam3InteractiveFrameContext,
    track_state: Sam3VideoAttentionTrackState,
    attention_temperature: float = 0.12,
    prototype_blend_weight: float = 0.35,
) -> Sam3MemoryAttentionPromptBuildResult:
    """根据历史对象 token memory 构造当前帧 prompt mask。"""

    feature_map = frame_context.low_res_feature_map.detach().float()
    if feature_map.ndim != 4 or feature_map.shape[0] != 1:
        raise ValueError(f"SAM3 视频 memory attention 期望 low_res_feature_map 形状为 (1,C,H,W)，实际得到 {tuple(feature_map.shape)}")
    feature_map = feature_map[0]
    channel_count, feature_height, feature_width = feature_map.shape
    feature_tokens = feature_map.permute(1, 2, 0).reshape(feature_height * feature_width, channel_count)
    normalized_feature_tokens = F.normalize(feature_tokens, dim=1)
    history_masks = [entry.low_res_mask for entry in track_state.memory_entries]
    history_mask = build_fused_history_mask_from_tensors(
        mask_history=history_masks,
        height=feature_height,
        width=feature_width,
        device=feature_map.device,
    )

    weighted_score_map = torch.zeros((feature_height * feature_width,), dtype=torch.float32, device=feature_map.device)
    attention_peak = 0.0
    entry_weights: list[float] = []
    for entry_index, memory_entry in enumerate(track_state.memory_entries):
        memory_tokens = memory_entry.object_tokens.detach().float()
        if memory_tokens.ndim != 2 or memory_tokens.shape[1] != channel_count:
            continue
        if memory_tokens.shape[0] <= 0:
            continue
        normalized_memory_tokens = F.normalize(
            memory_tokens.to(device=feature_map.device, dtype=normalized_feature_tokens.dtype),
            dim=1,
        )
        attention_logits = normalized_feature_tokens @ normalized_memory_tokens.transpose(0, 1)
        attention_response = float(attention_temperature) * torch.logsumexp(
            attention_logits / max(float(attention_temperature), 1e-6),
            dim=1,
        )
        min_response = attention_response.min()
        max_response = attention_response.max()
        normalized_response = (attention_response - min_response) / (max_response - min_response + 1e-6)
        temporal_weight = 0.68 ** float(len(track_state.memory_entries) - entry_index - 1)
        confidence_weight = max(0.15, float(memory_entry.score))
        current_weight = temporal_weight * confidence_weight
        weighted_score_map = weighted_score_map + (normalized_response * current_weight)
        entry_weights.append(current_weight)
        attention_peak = max(attention_peak, float(normalized_response.max().item()))

    if entry_weights:
        weighted_score_map = weighted_score_map / float(sum(entry_weights))
    weighted_score_map = weighted_score_map.reshape(feature_height, feature_width)

    prototype_ready = track_state.feature_prototype is not None
    if prototype_ready:
        prototype_map = _build_prototype_similarity_map(
            feature_map=feature_map,
            feature_prototype=track_state.feature_prototype.to(device=feature_map.device, dtype=feature_map.dtype),
        )
        if entry_weights:
            weighted_score_map = torch.maximum(weighted_score_map, prototype_map * float(prototype_blend_weight))
        else:
            weighted_score_map = prototype_map

    if history_mask is not None:
        weighted_score_map = torch.maximum(weighted_score_map, history_mask * 0.55)

    if not entry_weights and history_mask is None and not prototype_ready:
        raise ValueError("SAM3 memory-attention-tracker 构造 prompt 时缺少历史 entry、history mask 和 feature prototype")

    target_pixel_count = resolve_target_pixel_count(
        history_mask=history_mask,
        feature_height=feature_height,
        feature_width=feature_width,
    )
    low_res_binary_mask = _threshold_score_map(weighted_score_map, target_pixel_count=target_pixel_count)
    if history_mask is not None:
        low_res_binary_mask = torch.maximum(low_res_binary_mask, (history_mask > 0.45).to(dtype=torch.float32))
    low_res_binary_numpy = keep_largest_component(low_res_binary_mask.detach().cpu().numpy().astype(np.uint8))
    if int(low_res_binary_numpy.sum()) <= 0 and history_mask is not None:
        low_res_binary_numpy = (history_mask.detach().cpu().numpy() > 0.35).astype(np.uint8)
    prompt_mask = upsample_binary_mask(
        low_res_binary_numpy,
        width=frame_context.prepared_image.original_width,
        height=frame_context.prepared_image.original_height,
    )
    return Sam3MemoryAttentionPromptBuildResult(
        prompt_mask=prompt_mask,
        history_length=len(history_masks),
        attention_peak=attention_peak,
        prototype_ready=prototype_ready,
        memory_entry_count=len(track_state.memory_entries),
    )


def update_attention_track_state_from_region(
    *,
    track_state: Sam3VideoAttentionTrackState,
    frame_context: Sam3InteractiveFrameContext,
    region: Sam3RegionItem,
    frame_index: int,
    history_limit: int = 6,
    prototype_momentum: float = 0.7,
    max_memory_tokens_per_entry: int = 256,
) -> None:
    """用当前帧预测结果更新 attention 记忆状态。"""

    feature_map = frame_context.low_res_feature_map.detach().float()
    if feature_map.ndim != 4 or feature_map.shape[0] != 1:
        raise ValueError(f"SAM3 视频 attention 状态更新期望 low_res_feature_map 形状为 (1,C,H,W)，实际得到 {tuple(feature_map.shape)}")
    low_res_height = int(feature_map.shape[2])
    low_res_width = int(feature_map.shape[3])
    region_mask = decode_mask_png(region.mask_png_bytes)
    low_res_mask = resize_binary_mask(region_mask, width=low_res_width, height=low_res_height)
    if int(low_res_mask.sum()) <= 0:
        return
    low_res_mask_tensor = torch.from_numpy(low_res_mask).to(device=feature_map.device, dtype=torch.float32)
    object_tokens = _extract_object_tokens(
        feature_map=feature_map[0],
        low_res_mask=low_res_mask_tensor,
        max_memory_tokens_per_entry=max_memory_tokens_per_entry,
    )
    prototype = extract_feature_prototype(
        feature_map=feature_map[0],
        low_res_mask=low_res_mask_tensor,
    )
    if prototype is not None:
        prototype = prototype.detach().cpu()
        if track_state.feature_prototype is None:
            track_state.feature_prototype = prototype
        else:
            previous_prototype = track_state.feature_prototype.to(dtype=prototype.dtype)
            blended_prototype = (float(prototype_momentum) * previous_prototype) + ((1.0 - float(prototype_momentum)) * prototype)
            track_state.feature_prototype = F.normalize(blended_prototype, dim=0).detach().cpu()

    track_state.memory_entries.append(
        Sam3VideoAttentionMemoryEntry(
            object_tokens=object_tokens.detach().cpu(),
            low_res_mask=torch.from_numpy(low_res_mask.astype(np.float32)),
            score=float(region.score),
            frame_index=int(frame_index),
        )
    )
    if len(track_state.memory_entries) > int(history_limit):
        track_state.memory_entries = track_state.memory_entries[-int(history_limit) :]
    track_state.last_score = float(region.score)
    track_state.last_frame_index = int(frame_index)


def _extract_object_tokens(
    *,
    feature_map: torch.Tensor,
    low_res_mask: torch.Tensor,
    max_memory_tokens_per_entry: int,
) -> torch.Tensor:
    """从 low-res 特征图中提取对象 token 子集。"""

    channel_count, feature_height, feature_width = feature_map.shape
    flattened_mask = low_res_mask.reshape(-1) > 0.5
    feature_tokens = feature_map.permute(1, 2, 0).reshape(feature_height * feature_width, channel_count)
    selected_indices = torch.nonzero(flattened_mask, as_tuple=False).flatten()
    if int(selected_indices.numel()) <= 0:
        return F.normalize(feature_tokens[:1], dim=1)
    selected_tokens = feature_tokens.index_select(0, selected_indices)
    if int(selected_tokens.shape[0]) > int(max_memory_tokens_per_entry):
        sample_indices = torch.linspace(
            0,
            int(selected_tokens.shape[0]) - 1,
            steps=int(max_memory_tokens_per_entry),
            device=selected_tokens.device,
        ).round().long()
        selected_tokens = selected_tokens.index_select(0, sample_indices)
    return F.normalize(selected_tokens, dim=1)


def _build_prototype_similarity_map(
    *,
    feature_map: torch.Tensor,
    feature_prototype: torch.Tensor,
) -> torch.Tensor:
    """计算当前帧特征与对象原型的相似度热力图。"""

    channel_count, feature_height, feature_width = feature_map.shape
    feature_tokens = feature_map.permute(1, 2, 0).reshape(feature_height * feature_width, channel_count)
    normalized_tokens = F.normalize(feature_tokens, dim=1)
    normalized_prototype = F.normalize(feature_prototype.reshape(1, channel_count), dim=1)
    similarity_scores = torch.sum(normalized_tokens * normalized_prototype, dim=1).reshape(feature_height, feature_width)
    min_score = similarity_scores.min()
    max_score = similarity_scores.max()
    return (similarity_scores - min_score) / (max_score - min_score + 1e-6)


def _threshold_score_map(
    score_map: torch.Tensor,
    *,
    target_pixel_count: int,
) -> torch.Tensor:
    """按目标像素数把分数图转换成二值 mask。"""

    flattened_scores = score_map.reshape(-1)
    if target_pixel_count >= int(flattened_scores.numel()):
        return torch.ones_like(score_map, dtype=torch.float32)
    selected_indices = torch.topk(flattened_scores, k=max(1, int(target_pixel_count))).indices
    binary_mask = torch.zeros_like(flattened_scores, dtype=torch.float32)
    binary_mask[selected_indices] = 1.0
    return binary_mask.reshape_as(score_map)


__all__ = [
    "Sam3MemoryAttentionPromptBuildResult",
    "Sam3VideoAttentionMemoryEntry",
    "Sam3VideoAttentionTrackState",
    "build_memory_attention_prompt_mask",
    "update_attention_track_state_from_region",
]
