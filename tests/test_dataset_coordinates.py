"""统一数据集坐标与问题集合边界测试。"""

from __future__ import annotations

import math

import pytest

from backend.service.application.datasets.imports.issues import (
    DatasetIssue,
    DatasetIssueCollector,
)
from backend.service.domain.datasets.coordinates import (
    PASCAL_VOC_ONE_BASED_INCLUSIVE,
    PixelBox,
    ZERO_BASED_EXCLUSIVE,
)


def test_zero_based_exclusive_box_can_touch_all_image_boundaries() -> None:
    """验证默认框允许 0 原点以及 width/height exclusive 边界。"""

    box = PixelBox.from_external_xyxy(
        xmin=0,
        ymin=0,
        xmax=100,
        ymax=80,
        convention=ZERO_BASED_EXCLUSIVE,
        image_width=100,
        image_height=80,
    )

    assert box.to_xywh() == (0, 0, 100, 80)
    assert box.to_integer_xyxy(
        convention=ZERO_BASED_EXCLUSIVE,
        image_width=100,
        image_height=80,
    ) == (0, 0, 100, 80)


def test_official_pascal_voc_box_converts_to_internal_half_open_box() -> None:
    """验证显式官方 VOC 1-based inclusive 与内部坐标可逆。"""

    box = PixelBox.from_external_xyxy(
        xmin=1,
        ymin=1,
        xmax=100,
        ymax=80,
        convention=PASCAL_VOC_ONE_BASED_INCLUSIVE,
        image_width=100,
        image_height=80,
    )

    assert box.to_xywh() == (0, 0, 100, 80)
    assert box.to_integer_xyxy(
        convention=PASCAL_VOC_ONE_BASED_INCLUSIVE,
        image_width=100,
        image_height=80,
    ) == (1, 1, 100, 80)


def test_fractional_box_uses_outer_integer_quantization() -> None:
    """验证浮点框导出不会因整数化而缩小目标。"""

    box = PixelBox.from_xywh(
        (10.9, 20.1, 4.2, 5.3),
        image_width=100,
        image_height=80,
    )

    assert box.to_integer_xyxy(
        convention=ZERO_BASED_EXCLUSIVE,
        image_width=100,
        image_height=80,
    ) == (10, 20, 16, 26)


@pytest.mark.parametrize(
    "bbox_xywh",
    (
        (0.963281, 0.286111, 0.073438, 0.114815),
        (0.965365, 0.942593, 0.069271, 0.114815),
    ),
)
def test_yolo_normalized_box_absorbs_six_decimal_boundary_quantization(
    bbox_xywh: tuple[float, float, float, float],
) -> None:
    """验证贴右边界的六位 YOLO 标签不会因十进制量化变成越界框。"""

    box = PixelBox.from_yolo_normalized_xywh(
        bbox_xywh,
        image_width=1920,
        image_height=1080,
    )

    x, y, width, height = box.to_xywh()
    assert x + width == 1920.0
    assert 0.0 <= y < y + height <= 1080.0


def test_pixel_box_does_not_snap_real_out_of_bounds_values() -> None:
    """验证容差只处理运算残差，不掩盖真实越界标签。"""

    with pytest.raises(ValueError):
        PixelBox.from_yolo_normalized_xywh(
            (0.963283, 0.5, 0.073438, 0.1),
            image_width=1920,
            image_height=1080,
        )


@pytest.mark.parametrize(
    "bbox_xywh",
    [
        (math.nan, 0.0, 1.0, 1.0),
        (math.inf, 0.0, 1.0, 1.0),
        (0.0, 0.0, 0.0, 1.0),
        (-1.0, 0.0, 1.0, 1.0),
        (99.0, 0.0, 2.0, 1.0),
        (1e308, 0.0, 1e308, 1.0),
    ],
)
def test_pixel_box_rejects_non_finite_non_positive_and_out_of_range_values(
    bbox_xywh: tuple[float, float, float, float],
) -> None:
    """验证 NaN、Infinity、零面积、负数、溢出和越界均被拒绝。"""

    with pytest.raises(ValueError):
        PixelBox.from_xywh(
            bbox_xywh,
            image_width=100,
            image_height=80,
        )


def test_dataset_issue_collector_bounds_retained_memory() -> None:
    """验证问题总数可累计，但内存中的明细数量受硬上限控制。"""

    collector = DatasetIssueCollector(max_retained_issues=3)
    for index in range(10):
        collector.add(
            DatasetIssue(
                code=f"ISSUE_{index}",
                severity="error" if index % 2 == 0 else "warning",
                message="test",
            )
        )

    assert len(collector.issues) == 3
    assert collector.summary() == {
        "issue_count": 10,
        "error_count": 5,
        "warning_count": 5,
        "retained_issue_count": 3,
        "issues_truncated": True,
    }
