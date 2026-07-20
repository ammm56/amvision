"""OpenCV 搜索节点的高分辨率预算和结果上限测试。"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from custom_nodes._opencv_shared.backend.runtime.performance import (
    DEFAULT_FIND_RESULT_LIMIT,
    build_processing_image,
    read_find_result_limit,
    require_bounded_circle_search,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.hough_lines import _deduplicate_lines


def test_find_result_limit_uses_bounded_default_and_rejects_unlimited_values() -> None:
    """验证搜索节点空值默认返回 10，且 0/超大值不会变成无限结果。"""

    assert read_find_result_limit(None) == DEFAULT_FIND_RESULT_LIMIT == 10
    assert read_find_result_limit(3) == 3
    with pytest.raises(InvalidRequestError):
        read_find_result_limit(0)
    with pytest.raises(InvalidRequestError):
        read_find_result_limit(1001)


def test_processing_image_scales_20mp_input_and_preserves_coordinate_mapping() -> None:
    """验证 20MP 搜索图会缩到预算内，坐标比例仍可精确还原。"""

    source_matrix = np.zeros((3648, 5472), dtype=np.uint8)
    processing_image = build_processing_image(
        source_matrix,
        cv2_module=cv2,
        max_long_edge=2048,
    )

    assert processing_image.resized is True
    assert processing_image.processing_width == 2048
    assert processing_image.processing_height == 1365
    assert processing_image.processing_width * processing_image.scale_x_to_source == pytest.approx(5472)
    assert processing_image.processing_height * processing_image.scale_y_to_source == pytest.approx(3648)


def test_unbounded_hough_circle_rejects_20mp_search_before_opencv_call() -> None:
    """验证 20MP 全图无半径约束会快速失败，显式半径约束则允许执行。"""

    with pytest.raises(InvalidRequestError, match="高分辨率 Hough Circles"):
        require_bounded_circle_search(
            source_width=5472,
            source_height=3648,
            min_radius=0,
            max_radius=0,
        )
    require_bounded_circle_search(
        source_width=5472,
        source_height=3648,
        min_radius=20,
        max_radius=200,
    )


def test_hough_line_deduplicate_keeps_distinct_parallel_lines() -> None:
    """验证重复片段被合并，但距离足够远的平行线仍分别保留。"""

    line_items = [
        _line_item(start_xy=[0.0, 10.0], end_xy=[100.0, 10.0], line_index=1),
        _line_item(start_xy=[10.0, 11.0], end_xy=[90.0, 11.0], line_index=2),
        _line_item(start_xy=[0.0, 40.0], end_xy=[100.0, 40.0], line_index=3),
    ]

    result = _deduplicate_lines(
        line_items,
        angle_tolerance_deg=2.0,
        distance_tolerance_pixels=4.0,
    )

    assert len(result) == 2
    assert [item["line_index"] for item in result] == [1, 2]
    assert [item["midpoint_y"] for item in result] == [10.0, 40.0]


def _line_item(*, start_xy: list[float], end_xy: list[float], line_index: int) -> dict[str, object]:
    """构造 Hough line 去重测试所需的最小结果结构。"""

    midpoint_x = (start_xy[0] + end_xy[0]) / 2.0
    midpoint_y = (start_xy[1] + end_xy[1]) / 2.0
    return {
        "line_index": line_index,
        "start_xy": start_xy,
        "end_xy": end_xy,
        "angle_deg": 0.0,
        "midpoint_xy": [midpoint_x, midpoint_y],
        "midpoint_x": midpoint_x,
        "midpoint_y": midpoint_y,
        "length_pixels": end_xy[0] - start_xy[0],
    }
