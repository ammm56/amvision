"""regions.v1 连通域、空洞和跨度底层计算。"""

from __future__ import annotations

import cv2
import numpy as np


def compute_component_areas(mask_matrix: np.ndarray) -> list[int]:
    """计算前景连通域面积列表，按面积从大到小排序。"""

    binary_mask = (mask_matrix > 0).astype(np.uint8)
    if int(np.count_nonzero(binary_mask)) <= 0:
        return []
    label_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        binary_mask,
        connectivity=8,
    )
    component_areas = [
        int(stats[label_index, cv2.CC_STAT_AREA])
        for label_index in range(1, label_count)
        if int(stats[label_index, cv2.CC_STAT_AREA]) > 0
    ]
    component_areas.sort(reverse=True)
    return component_areas


def compute_hole_areas(mask_matrix: np.ndarray) -> list[int]:
    """计算空洞面积列表，按面积从大到小排序。"""

    binary_mask = (mask_matrix > 0).astype(np.uint8)
    padded_mask = np.pad(binary_mask, pad_width=1, mode="constant", constant_values=0)
    background_mask = (padded_mask == 0).astype(np.uint8)
    label_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        background_mask,
        connectivity=8,
    )
    hole_areas = [
        int(stats[label_index, cv2.CC_STAT_AREA])
        for label_index in range(1, label_count)
        if int(stats[label_index, cv2.CC_STAT_AREA]) > 0
        and not _touches_outer_border(labels == label_index)
    ]
    hole_areas.sort(reverse=True)
    return hole_areas


def compute_span_metrics(mask_matrix: np.ndarray) -> dict[str, object]:
    """计算单个二值区域的跨度、方向和细长度。"""

    foreground_points = np.column_stack(np.nonzero(mask_matrix > 0))
    if foreground_points.size <= 0:
        return {
            "x_span_pixels": 0,
            "y_span_pixels": 0,
            "long_span_pixels": 0.0,
            "short_span_pixels": 0.0,
            "elongation_ratio": None,
            "orientation_deg": None,
            "axis_aligned_fill_ratio": None,
        }
    y_values = foreground_points[:, 0]
    x_values = foreground_points[:, 1]
    x_span_pixels = int(np.max(x_values) - np.min(x_values) + 1)
    y_span_pixels = int(np.max(y_values) - np.min(y_values) + 1)
    if foreground_points.shape[0] == 1:
        long_span_pixels = 1.0
        short_span_pixels = 1.0
        orientation_deg = 0.0
    else:
        point_cloud = np.column_stack((x_values.astype(np.float32), y_values.astype(np.float32)))
        _center, size, angle = cv2.minAreaRect(point_cloud)
        width_value = max(1.0, float(size[0]))
        height_value = max(1.0, float(size[1]))
        if width_value >= height_value:
            long_span_pixels = width_value
            short_span_pixels = height_value
            orientation_deg = float(angle)
        else:
            long_span_pixels = height_value
            short_span_pixels = width_value
            orientation_deg = float(angle + 90.0)
        orientation_deg = float(orientation_deg % 180.0)
        if orientation_deg >= 90.0:
            orientation_deg -= 180.0
    axis_aligned_area = max(1, x_span_pixels * y_span_pixels)
    elongation_ratio = float(long_span_pixels / short_span_pixels) if short_span_pixels > 0 else None
    return {
        "x_span_pixels": x_span_pixels,
        "y_span_pixels": y_span_pixels,
        "long_span_pixels": float(long_span_pixels),
        "short_span_pixels": float(short_span_pixels),
        "elongation_ratio": elongation_ratio,
        "orientation_deg": orientation_deg,
        "axis_aligned_fill_ratio": float(int(foreground_points.shape[0]) / axis_aligned_area),
    }


def _touches_outer_border(label_mask: np.ndarray) -> bool:
    """判断一个背景连通域是否接触外边界。"""

    return bool(
        np.any(label_mask[0, :])
        or np.any(label_mask[-1, :])
        or np.any(label_mask[:, 0])
        or np.any(label_mask[:, -1])
    )

