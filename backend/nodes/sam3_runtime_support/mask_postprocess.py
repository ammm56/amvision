"""SAM3 interactive mask 后处理。"""

from __future__ import annotations

from dataclasses import dataclass
import io
from typing import Protocol

import cv2
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F


class Sam3InteractivePromptLike(Protocol):
    """描述 SAM3 interactive prompt 最小字段协议。"""

    prompt_id: str
    display_name: str


@dataclass(frozen=True)
class Sam3RegionItem:
    """描述一条已完成后处理的 region。"""

    region_id: str
    score: float
    class_id: int
    class_name: str
    bbox_xyxy: tuple[float, float, float, float]
    polygon_xy: tuple[tuple[float, float], ...]
    area: int
    prompt_id: str
    mask_png_bytes: bytes
    mask_width: int
    mask_height: int


def postprocess_sam3_interactive_masks(
    mask_logits: torch.Tensor,
    *,
    source_width: int,
    source_height: int,
    prompt_items: tuple[Sam3InteractivePromptLike, ...],
    scores: torch.Tensor | None = None,
    threshold: float = 0.0,
) -> tuple[Sam3RegionItem, ...]:
    """把 SAM3 interactive 的 mask logits 规整为 regions.v1 可消费的结果。"""

    if mask_logits.ndim == 4 and mask_logits.shape[1] == 1:
        mask_logits = mask_logits[:, 0]
    if mask_logits.ndim != 3:
        raise ValueError(f"mask_logits 期望形状为 (N,H,W) 或 (N,1,H,W)，实际得到 {tuple(mask_logits.shape)}")

    resized_masks = F.interpolate(
        mask_logits.unsqueeze(1).float(),
        size=(source_height, source_width),
        mode="bilinear",
        align_corners=False,
    )[:, 0]
    normalized_scores = (
        scores.detach().float().cpu().view(-1).tolist()
        if torch.is_tensor(scores)
        else [1.0] * int(resized_masks.shape[0])
    )
    region_items: list[Sam3RegionItem] = []
    for index, mask_tensor in enumerate(resized_masks):
        binary_mask = (mask_tensor > threshold).to(dtype=torch.uint8).cpu().numpy()
        if int(binary_mask.sum()) <= 0:
            continue
        bbox_xyxy = _build_bbox_xyxy_from_mask(binary_mask)
        polygon_xy = _build_polygon_xy_from_mask(binary_mask, fallback_bbox_xyxy=bbox_xyxy)
        area = int(np.count_nonzero(binary_mask))
        mask_png_bytes = _encode_mask_png(binary_mask)
        prompt_item = prompt_items[index] if index < len(prompt_items) else None
        class_name = prompt_item.display_name if prompt_item is not None else f"prompt-{index + 1}"
        prompt_id = prompt_item.prompt_id if prompt_item is not None else f"prompt-{index + 1}"
        region_items.append(
            Sam3RegionItem(
                region_id=f"region-{index + 1}",
                score=float(normalized_scores[index]) if index < len(normalized_scores) else 1.0,
                class_id=index,
                class_name=class_name,
                bbox_xyxy=bbox_xyxy,
                polygon_xy=polygon_xy,
                area=area,
                prompt_id=prompt_id,
                mask_png_bytes=mask_png_bytes,
                mask_width=source_width,
                mask_height=source_height,
            )
        )
    return tuple(region_items)


def _build_bbox_xyxy_from_mask(binary_mask: np.ndarray) -> tuple[float, float, float, float]:
    """从二值 mask 中提取 bbox。"""

    ys, xs = np.nonzero(binary_mask)
    if len(xs) == 0 or len(ys) == 0:
        return (0.0, 0.0, 0.0, 0.0)
    x1_value = float(xs.min())
    y1_value = float(ys.min())
    x2_value = float(xs.max())
    y2_value = float(ys.max())
    return (x1_value, y1_value, x2_value, y2_value)


def _build_polygon_xy_from_mask(
    binary_mask: np.ndarray,
    *,
    fallback_bbox_xyxy: tuple[float, float, float, float],
) -> tuple[tuple[float, float], ...]:
    """从二值 mask 中提取 polygon，失败时回退到 bbox polygon。"""

    contour_result = cv2.findContours(binary_mask.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = contour_result[0] if len(contour_result) == 2 else contour_result[1]
    if not contours:
        return _build_bbox_polygon_xy(fallback_bbox_xyxy)
    contour = max(contours, key=cv2.contourArea)
    epsilon = 0.002 * cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, epsilon, True)
    if approx.ndim != 3 or approx.shape[0] < 3:
        return _build_bbox_polygon_xy(fallback_bbox_xyxy)
    return tuple((float(point[0][0]), float(point[0][1])) for point in approx)


def _build_bbox_polygon_xy(bbox_xyxy: tuple[float, float, float, float]) -> tuple[tuple[float, float], ...]:
    """把 bbox 转换成四点 polygon。"""

    x1_value, y1_value, x2_value, y2_value = bbox_xyxy
    return (
        (float(x1_value), float(y1_value)),
        (float(x2_value), float(y1_value)),
        (float(x2_value), float(y2_value)),
        (float(x1_value), float(y2_value)),
    )


def _encode_mask_png(binary_mask: np.ndarray) -> bytes:
    """把二值 mask 编码为 PNG。"""

    encoded_image = Image.fromarray((binary_mask > 0).astype(np.uint8) * 255, mode="L")
    buffer = io.BytesIO()
    encoded_image.save(buffer, format="PNG")
    return buffer.getvalue()
