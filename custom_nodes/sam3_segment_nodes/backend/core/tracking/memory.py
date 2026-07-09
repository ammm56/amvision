"""SAM3 视频 interactive 的对象记忆与多帧状态跟踪 helper。"""

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


@dataclass
class Sam3VideoTrackState:
    """描述一个视频交互对象在多帧中的记忆状态。"""

    prompt_id: str
    display_name: str
    feature_prototype: torch.Tensor | None = None
    low_res_mask_history: list[torch.Tensor] = field(default_factory=list)
    last_score: float = 0.0
    last_frame_index: int | None = None


@dataclass(frozen=True)
class Sam3MemoryPromptBuildResult:
    """描述一次对象记忆 prompt 构造结果。"""

    prompt_mask: np.ndarray
    history_length: int
    similarity_peak: float
    prototype_ready: bool


def build_memory_prompt_mask(
    *,
    frame_context: Sam3InteractiveFrameContext,
    track_state: Sam3VideoTrackState,
) -> Sam3MemoryPromptBuildResult:
    """根据当前帧特征与历史状态生成高分辨率 memory prompt mask。"""

    feature_map = frame_context.low_res_feature_map.detach().float()
    if feature_map.ndim != 4 or feature_map.shape[0] != 1:
        raise ValueError(f"SAM3 视频 memory prompt 期望 low_res_feature_map 形状为 (1,C,H,W)，实际得到 {tuple(feature_map.shape)}")
    feature_map = feature_map[0]
    feature_height = int(feature_map.shape[1])
    feature_width = int(feature_map.shape[2])
    history_mask = _build_fused_history_mask(
        mask_history=track_state.low_res_mask_history,
        height=feature_height,
        width=feature_width,
        device=feature_map.device,
    )
    prototype_ready = track_state.feature_prototype is not None
    similarity_peak = 0.0
    if prototype_ready:
        similarity_map = _build_similarity_map(
            feature_map=feature_map,
            feature_prototype=track_state.feature_prototype.to(device=feature_map.device, dtype=feature_map.dtype),
        )
        similarity_peak = float(similarity_map.max().item()) if similarity_map.numel() > 0 else 0.0
        combined_score_map = similarity_map
        if history_mask is not None:
            combined_score_map = torch.maximum(similarity_map, history_mask * 0.75)
        target_pixel_count = _resolve_target_pixel_count(
            history_mask=history_mask,
            feature_height=feature_height,
            feature_width=feature_width,
        )
        low_res_binary_mask = _threshold_score_map(
            combined_score_map,
            target_pixel_count=target_pixel_count,
        )
        if history_mask is not None:
            low_res_binary_mask = torch.maximum(low_res_binary_mask, (history_mask > 0.45).to(dtype=torch.float32))
    elif history_mask is not None:
        low_res_binary_mask = (history_mask > 0.35).to(dtype=torch.float32)
    else:
        raise ValueError("SAM3 视频 memory prompt 构造要求至少存在历史 mask 或 feature prototype")

    low_res_binary_numpy = _keep_largest_component(low_res_binary_mask.detach().cpu().numpy().astype(np.uint8))
    if int(low_res_binary_numpy.sum()) <= 0 and history_mask is not None:
        low_res_binary_numpy = (history_mask.detach().cpu().numpy() > 0.35).astype(np.uint8)
    prompt_mask = _upsample_binary_mask(
        low_res_binary_numpy,
        width=frame_context.prepared_image.original_width,
        height=frame_context.prepared_image.original_height,
    )
    return Sam3MemoryPromptBuildResult(
        prompt_mask=prompt_mask,
        history_length=len(track_state.low_res_mask_history),
        similarity_peak=similarity_peak,
        prototype_ready=prototype_ready,
    )


def update_track_state_from_region(
    *,
    track_state: Sam3VideoTrackState,
    frame_context: Sam3InteractiveFrameContext,
    region: Sam3RegionItem,
    frame_index: int,
    history_limit: int = 4,
    prototype_momentum: float = 0.7,
) -> None:
    """用当前帧预测结果更新对象记忆状态。"""

    feature_map = frame_context.low_res_feature_map.detach().float()
    if feature_map.ndim != 4 or feature_map.shape[0] != 1:
        raise ValueError(f"SAM3 视频状态更新期望 low_res_feature_map 形状为 (1,C,H,W)，实际得到 {tuple(feature_map.shape)}")
    low_res_height = int(feature_map.shape[2])
    low_res_width = int(feature_map.shape[3])
    region_mask = _resolve_region_mask_array(region)
    low_res_mask = _resize_binary_mask(
        region_mask,
        width=low_res_width,
        height=low_res_height,
    )
    if int(low_res_mask.sum()) <= 0:
        return
    prototype = _extract_feature_prototype(
        feature_map=feature_map[0],
        low_res_mask=torch.from_numpy(low_res_mask).to(device=feature_map.device, dtype=torch.float32),
    )
    if prototype is not None:
        prototype = prototype.detach().cpu()
        if track_state.feature_prototype is None:
            track_state.feature_prototype = prototype
        else:
            previous_prototype = track_state.feature_prototype.to(dtype=prototype.dtype)
            blended_prototype = (float(prototype_momentum) * previous_prototype) + ((1.0 - float(prototype_momentum)) * prototype)
            track_state.feature_prototype = F.normalize(blended_prototype, dim=0).detach().cpu()
    track_state.low_res_mask_history.append(torch.from_numpy(low_res_mask.astype(np.float32)))
    if len(track_state.low_res_mask_history) > int(history_limit):
        track_state.low_res_mask_history = track_state.low_res_mask_history[-int(history_limit) :]
    track_state.last_score = float(region.score)
    track_state.last_frame_index = int(frame_index)


def _build_fused_history_mask(
    *,
    mask_history: list[torch.Tensor],
    height: int,
    width: int,
    device: torch.device,
) -> torch.Tensor | None:
    """把最近若干帧 low-res mask 做指数加权融合。"""

    return build_fused_history_mask_from_tensors(
        mask_history=mask_history,
        height=height,
        width=width,
        device=device,
    )


def _build_similarity_map(
    *,
    feature_map: torch.Tensor,
    feature_prototype: torch.Tensor,
) -> torch.Tensor:
    """计算当前帧特征与对象原型的余弦相似度热力图。"""

    channel_count, feature_height, feature_width = feature_map.shape
    feature_tokens = feature_map.permute(1, 2, 0).reshape(feature_height * feature_width, channel_count)
    normalized_tokens = F.normalize(feature_tokens, dim=1)
    normalized_prototype = F.normalize(feature_prototype.reshape(1, channel_count), dim=1)
    similarity_scores = torch.sum(normalized_tokens * normalized_prototype, dim=1).reshape(feature_height, feature_width)
    min_score = similarity_scores.min()
    max_score = similarity_scores.max()
    return (similarity_scores - min_score) / (max_score - min_score + 1e-6)


def _resolve_target_pixel_count(
    *,
    history_mask: torch.Tensor | None,
    feature_height: int,
    feature_width: int,
) -> int:
    """根据历史对象面积估算当前帧目标占用像素数。"""

    return resolve_target_pixel_count(
        history_mask=history_mask,
        feature_height=feature_height,
        feature_width=feature_width,
    )


def _threshold_score_map(
    score_map: torch.Tensor,
    *,
    target_pixel_count: int,
) -> torch.Tensor:
    """按目标像素数把分数图转换成二值 mask。"""

    flattened_scores = score_map.reshape(-1)
    if target_pixel_count >= int(flattened_scores.numel()):
        return torch.ones_like(score_map, dtype=torch.float32)
    topk_values, _topk_indices = torch.topk(flattened_scores, k=max(1, int(target_pixel_count)))
    threshold_value = topk_values[-1]
    return (score_map >= threshold_value).to(dtype=torch.float32)


def _keep_largest_component(binary_mask: np.ndarray) -> np.ndarray:
    """仅保留二值 mask 中面积最大的连通域。"""

    return keep_largest_component(binary_mask)


def _upsample_binary_mask(binary_mask: np.ndarray, *, width: int, height: int) -> np.ndarray:
    """把 low-res 二值 mask 放大回源图分辨率。"""

    return upsample_binary_mask(binary_mask, width=width, height=height)


def _resize_binary_mask(binary_mask: np.ndarray, *, width: int, height: int) -> np.ndarray:
    """把源图二值 mask 缩放到 low-res 特征图分辨率。"""

    return resize_binary_mask(binary_mask, width=width, height=height)


def _resolve_region_mask_array(region: Sam3RegionItem) -> np.ndarray:
    """读取 region 中保留的 mask array，必要时退回 PNG bytes 解码。"""

    mask_array = getattr(region, "mask_array", None)
    if isinstance(mask_array, np.ndarray):
        return (mask_array > 0).astype(np.uint8)
    return _decode_mask_png(region.mask_png_bytes)


def _decode_mask_png(mask_png_bytes: bytes) -> np.ndarray:
    """把 PNG mask 解码成二维二值数组。"""

    return decode_mask_png(mask_png_bytes)


def _extract_feature_prototype(
    *,
    feature_map: torch.Tensor,
    low_res_mask: torch.Tensor,
) -> torch.Tensor | None:
    """从当前帧特征图中提取对象原型向量。"""

    return extract_feature_prototype(feature_map=feature_map, low_res_mask=low_res_mask)


__all__ = [
    "Sam3MemoryPromptBuildResult",
    "Sam3VideoTrackState",
    "build_memory_prompt_mask",
    "update_track_state_from_region",
]
