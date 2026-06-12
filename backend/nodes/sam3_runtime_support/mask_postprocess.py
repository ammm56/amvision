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
    source_prompt_text: str | None = None
    source_prompt_positive_texts: tuple[str, ...] | None = None
    source_prompt_negative_texts: tuple[str, ...] | None = None


DEFAULT_MASK_THRESHOLD = 0.0
DEFAULT_STABILITY_OFFSET = 0.05
DEFAULT_POLYGON_SIMPLIFY_RATIO = 0.002


def postprocess_sam3_interactive_masks(
    mask_logits: torch.Tensor,
    *,
    source_width: int,
    source_height: int,
    prompt_items: tuple[Sam3InteractivePromptLike, ...],
    scores: torch.Tensor | None = None,
    threshold: float = DEFAULT_MASK_THRESHOLD,
    stability_offset: float = DEFAULT_STABILITY_OFFSET,
    polygon_simplify_ratio: float = DEFAULT_POLYGON_SIMPLIFY_RATIO,
    min_component_area: int | None = None,
    min_region_area: int | None = None,
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
    normalized_scores = scores.detach().float().cpu().view(-1).tolist() if torch.is_tensor(scores) else None
    resolved_min_component_area = _resolve_min_component_area(
        source_width=source_width,
        source_height=source_height,
        explicit_value=min_component_area,
    )
    resolved_min_region_area = _resolve_min_region_area(
        source_width=source_width,
        source_height=source_height,
        min_component_area=resolved_min_component_area,
        explicit_value=min_region_area,
    )
    region_items: list[Sam3RegionItem] = []
    for index, mask_tensor in enumerate(resized_masks):
        logits_array = mask_tensor.detach().float().cpu().numpy()
        binary_mask = (logits_array > threshold).astype(np.uint8)
        if int(binary_mask.sum()) <= 0:
            continue
        filtered_mask = _filter_small_components(binary_mask, min_component_area=resolved_min_component_area)
        filtered_area = int(np.count_nonzero(filtered_mask))
        if filtered_area < resolved_min_region_area:
            continue
        bbox_xyxy = _build_bbox_xyxy_from_mask(filtered_mask)
        polygon_xy = _build_polygon_xy_from_mask(
            filtered_mask,
            fallback_bbox_xyxy=bbox_xyxy,
            simplify_ratio=polygon_simplify_ratio,
        )
        stability_score = _compute_mask_stability(
            logits_array,
            threshold=threshold,
            stability_offset=stability_offset,
        )
        explicit_score = (
            float(normalized_scores[index])
            if normalized_scores is not None and index < len(normalized_scores)
            else None
        )
        region_score = _resolve_region_score(
            logits_array,
            filtered_mask,
            explicit_score=explicit_score,
            stability_score=stability_score,
        )
        mask_png_bytes = _encode_mask_png(filtered_mask)
        prompt_item = prompt_items[index] if index < len(prompt_items) else None
        class_name = prompt_item.display_name if prompt_item is not None else f"prompt-{index + 1}"
        prompt_id = prompt_item.prompt_id if prompt_item is not None else f"prompt-{index + 1}"
        region_items.append(
            Sam3RegionItem(
                region_id=f"region-{index + 1}",
                score=region_score,
                class_id=index,
                class_name=class_name,
                bbox_xyxy=bbox_xyxy,
                polygon_xy=polygon_xy,
                area=filtered_area,
                prompt_id=prompt_id,
                mask_png_bytes=mask_png_bytes,
                mask_width=source_width,
                mask_height=source_height,
                source_prompt_text=(
                    str(getattr(prompt_item, "source_prompt_text"))
                    if prompt_item is not None and getattr(prompt_item, "source_prompt_text", None) is not None
                    else None
                ),
                source_prompt_positive_texts=(
                    tuple(str(item) for item in getattr(prompt_item, "source_prompt_positive_texts"))
                    if prompt_item is not None and getattr(prompt_item, "source_prompt_positive_texts", None) is not None
                    else None
                ),
                source_prompt_negative_texts=(
                    tuple(str(item) for item in getattr(prompt_item, "source_prompt_negative_texts"))
                    if prompt_item is not None and getattr(prompt_item, "source_prompt_negative_texts", None) is not None
                    else None
                ),
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
    simplify_ratio: float,
) -> tuple[tuple[float, float], ...]:
    """从二值 mask 中提取 polygon，失败时回退到 bbox polygon。"""

    contour_result = cv2.findContours(binary_mask.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = contour_result[0] if len(contour_result) == 2 else contour_result[1]
    if not contours:
        return _build_bbox_polygon_xy(fallback_bbox_xyxy)
    contour = max(contours, key=cv2.contourArea)
    epsilon = float(max(0.0, simplify_ratio)) * cv2.arcLength(contour, True)
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


def _resolve_min_component_area(
    *,
    source_width: int,
    source_height: int,
    explicit_value: int | None,
) -> int:
    """解析小连通域过滤阈值。"""

    if explicit_value is not None:
        return max(0, int(explicit_value))
    return max(9, int(round(float(source_width * source_height) * 0.0001)))


def _resolve_min_region_area(
    *,
    source_width: int,
    source_height: int,
    min_component_area: int,
    explicit_value: int | None,
) -> int:
    """解析最小区域面积阈值。"""

    if explicit_value is not None:
        return max(0, int(explicit_value))
    return max(min_component_area, max(16, int(round(float(source_width * source_height) * 0.0002))))


def _filter_small_components(
    binary_mask: np.ndarray,
    *,
    min_component_area: int,
) -> np.ndarray:
    """过滤掉面积过小的连通域。"""

    if min_component_area <= 1:
        return binary_mask.astype(np.uint8)
    component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        binary_mask.astype(np.uint8),
        connectivity=8,
    )
    if component_count <= 1:
        return binary_mask.astype(np.uint8)
    filtered_mask = np.zeros_like(binary_mask, dtype=np.uint8)
    for component_index in range(1, component_count):
        component_area = int(stats[component_index, cv2.CC_STAT_AREA])
        if component_area >= min_component_area:
            filtered_mask[labels == component_index] = 1
    return filtered_mask


def _compute_mask_stability(
    logits_array: np.ndarray,
    *,
    threshold: float,
    stability_offset: float,
) -> float:
    """按高低阈值交并比估算 mask 稳定性。"""

    low_threshold_mask = logits_array > float(threshold) - float(stability_offset)
    union_area = int(np.count_nonzero(low_threshold_mask))
    if union_area <= 0:
        return 0.0
    high_threshold_mask = logits_array > float(threshold) + float(stability_offset)
    intersection_area = int(np.count_nonzero(high_threshold_mask))
    return float(intersection_area) / float(union_area)


def _resolve_region_score(
    logits_array: np.ndarray,
    filtered_mask: np.ndarray,
    *,
    explicit_score: float | None,
    stability_score: float,
) -> float:
    """融合显式 score、mask 置信度和稳定性分数。"""

    if explicit_score is not None:
        base_score = float(explicit_score)
    else:
        positive_logits = logits_array[filtered_mask > 0]
        if positive_logits.size <= 0:
            base_score = 0.0
        else:
            positive_confidence = torch.sigmoid(
                torch.from_numpy(positive_logits.astype(np.float32))
            ).mean().item()
            base_score = float(positive_confidence)
    normalized_score = 0.5 * float(base_score) + 0.5 * float(stability_score)
    return float(np.clip(normalized_score, 0.0, 1.0))
