"""Draw Regions 通用标签与配色规则测试。"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.categories.render.backend.nodes.draw_regions import (
    _build_region_label,
    _pick_overlay_color,
    _read_boolean_parameter,
    _read_class_colors,
)


def test_draw_regions_label_can_show_id_class_and_score_together() -> None:
    """分类结果标签应能同时保留 ROI ID、类别和分数。"""

    label = _build_region_label(
        {
            "region_id": "roi-01-02",
            "class_name": "slot_empty",
            "score": 0.987,
        },
        draw_region_id=True,
        draw_class_name=True,
        draw_score=True,
    )

    assert label == "roi-01-02 slot_empty 0.99"


def test_draw_regions_class_name_color_is_stable_across_regions() -> None:
    """按类别配色时，同类不同 ROI 必须使用同一颜色。"""

    first = _pick_overlay_color(
        {"region_id": "roi-a", "class_name": "slot_empty"},
        cv2_module=cv2,
        np_module=np,
        color_by="class-name",
        class_colors={},
    )
    second = _pick_overlay_color(
        {"region_id": "roi-b", "class_name": "slot_empty"},
        cv2_module=cv2,
        np_module=np,
        color_by="class-name",
        class_colors={},
    )

    assert first == second


def test_draw_regions_class_color_override_uses_rgb_configuration() -> None:
    """#RRGGBB 配置应转换成 OpenCV BGR。"""

    class_colors = _read_class_colors({"slot_empty": "#12ABEF"})
    color = _pick_overlay_color(
        {"region_id": "roi-a", "class_name": "slot_empty"},
        cv2_module=cv2,
        np_module=np,
        color_by="class-name",
        class_colors=class_colors,
    )

    assert color == (0xEF, 0xAB, 0x12)


def test_draw_regions_rejects_implicit_boolean_and_invalid_color() -> None:
    """参数不得依赖字符串 truthy 等隐式行为。"""

    with pytest.raises(InvalidRequestError, match="draw_labels 必须是 boolean"):
        _read_boolean_parameter("false", field_name="draw_labels", default=True)
    with pytest.raises(InvalidRequestError, match="#RRGGBB"):
        _read_class_colors({"slot_empty": "red"})
