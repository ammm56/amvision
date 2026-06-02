"""SAM3 视频跟踪模块共享的 mask/特征 helper。"""

from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F


def build_fused_history_mask_from_tensors(
    *,
    mask_history: list[torch.Tensor],
    height: int,
    width: int,
    device: torch.device,
) -> torch.Tensor | None:
    """把最近若干帧 low-res mask 做指数加权融合。"""

    if not mask_history:
        return None
    normalized_masks: list[torch.Tensor] = []
    for mask_tensor in mask_history:
        current_mask = mask_tensor.detach().float()
        if current_mask.ndim != 2:
            raise ValueError(f"SAM3 low-res mask history 期望二维张量，实际得到 {tuple(current_mask.shape)}")
        if tuple(current_mask.shape) != (height, width):
            current_mask = F.interpolate(
                current_mask.unsqueeze(0).unsqueeze(0),
                size=(height, width),
                mode="nearest",
            )[0, 0]
        normalized_masks.append(current_mask.to(device=device))
    weights = torch.tensor(
        [0.6 ** float(len(normalized_masks) - index - 1) for index in range(len(normalized_masks))],
        dtype=torch.float32,
        device=device,
    )
    stacked_masks = torch.stack(normalized_masks, dim=0)
    fused_mask = (stacked_masks * weights.view(-1, 1, 1)).sum(dim=0) / weights.sum()
    return fused_mask.clamp(0.0, 1.0)


def resolve_target_pixel_count(
    *,
    history_mask: torch.Tensor | None,
    feature_height: int,
    feature_width: int,
) -> int:
    """根据历史对象面积估算当前帧目标占用像素数。"""

    feature_pixel_count = int(feature_height * feature_width)
    if history_mask is None:
        return max(6, int(round(feature_pixel_count * 0.08)))
    history_area = int((history_mask > 0.35).sum().item())
    if history_area <= 0:
        return max(6, int(round(feature_pixel_count * 0.08)))
    return max(6, min(feature_pixel_count, int(round(history_area * 1.35))))


def keep_largest_component(binary_mask: np.ndarray) -> np.ndarray:
    """仅保留二值 mask 中面积最大的连通域。"""

    component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(binary_mask.astype(np.uint8), connectivity=8)
    if component_count <= 1:
        return binary_mask.astype(np.uint8)
    largest_component_index = 1
    largest_component_area = int(stats[1, cv2.CC_STAT_AREA])
    for component_index in range(2, component_count):
        current_area = int(stats[component_index, cv2.CC_STAT_AREA])
        if current_area > largest_component_area:
            largest_component_index = component_index
            largest_component_area = current_area
    filtered_mask = np.zeros_like(binary_mask, dtype=np.uint8)
    filtered_mask[labels == largest_component_index] = 1
    return filtered_mask


def upsample_binary_mask(binary_mask: np.ndarray, *, width: int, height: int) -> np.ndarray:
    """把 low-res 二值 mask 放大回源图分辨率。"""

    mask_tensor = torch.from_numpy(binary_mask.astype(np.float32)).unsqueeze(0).unsqueeze(0)
    upsampled_mask = F.interpolate(mask_tensor, size=(height, width), mode="nearest")[0, 0]
    return (upsampled_mask.detach().cpu().numpy() > 0).astype(np.uint8)


def resize_binary_mask(binary_mask: np.ndarray, *, width: int, height: int) -> np.ndarray:
    """把源图二值 mask 缩放到 low-res 特征图分辨率。"""

    mask_tensor = torch.from_numpy(binary_mask.astype(np.float32)).unsqueeze(0).unsqueeze(0)
    resized_mask = F.interpolate(mask_tensor, size=(height, width), mode="nearest")[0, 0]
    return (resized_mask.detach().cpu().numpy() > 0).astype(np.uint8)


def decode_mask_png(mask_png_bytes: bytes) -> np.ndarray:
    """把 PNG mask 解码成二维二值数组。"""

    decoded_image = Image.open(io.BytesIO(mask_png_bytes)).convert("L")
    return (np.asarray(decoded_image, dtype=np.uint8) > 0).astype(np.uint8)


def extract_feature_prototype(
    *,
    feature_map: torch.Tensor,
    low_res_mask: torch.Tensor,
) -> torch.Tensor | None:
    """从当前帧特征图中提取对象原型向量。"""

    if feature_map.ndim != 3:
        raise ValueError(f"SAM3 feature_map 期望三维张量，实际得到 {tuple(feature_map.shape)}")
    if low_res_mask.ndim != 2:
        raise ValueError(f"SAM3 low_res_mask 期望二维张量，实际得到 {tuple(low_res_mask.shape)}")
    channel_count, feature_height, feature_width = feature_map.shape
    if tuple(low_res_mask.shape) != (feature_height, feature_width):
        raise ValueError("SAM3 low_res_mask 尺寸必须与 feature_map 空间尺寸一致")
    normalized_mask = low_res_mask.reshape(-1).clamp(min=0.0)
    mask_sum = float(normalized_mask.sum().item())
    if mask_sum <= 0.0:
        return None
    feature_tokens = feature_map.permute(1, 2, 0).reshape(feature_height * feature_width, channel_count)
    prototype = (feature_tokens * normalized_mask.unsqueeze(1)).sum(dim=0) / normalized_mask.sum()
    return F.normalize(prototype, dim=0)


__all__ = [
    "build_fused_history_mask_from_tensors",
    "decode_mask_png",
    "extract_feature_prototype",
    "keep_largest_component",
    "resize_binary_mask",
    "resolve_target_pixel_count",
    "upsample_binary_mask",
]
