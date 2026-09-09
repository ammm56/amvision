"""Draw Regions 通用标签与配色规则测试。"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from types import SimpleNamespace

from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.categories.render.backend.nodes import draw_regions
from custom_nodes.opencv_nodes.categories.render.backend.nodes.draw_regions import (
    _build_region_label,
    _pick_overlay_color,
    _read_boolean_parameter,
    _read_class_colors,
    _read_label_offset,
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


@pytest.mark.parametrize("value", [True, "-8", "", 1.5, float("nan"), float("inf"), 2**31, -(2**31)-1])
def test_draw_regions_rejects_invalid_offsets(value: object) -> None:
    """非法偏移应在调用 OpenCV 前给出参数错误。"""

    with pytest.raises(InvalidRequestError, match="label_offset_x"):
        _read_label_offset(value, field_name="label_offset_x")


@pytest.mark.parametrize("offset", [None, (0, 0), (12, 18), (-12, -18), (-45, -35), (2147483647, 0)])
@pytest.mark.parametrize("draw_labels", [True, False])
def test_draw_regions_offsets_preserve_boxes_and_source_pixels(
    monkeypatch: pytest.MonkeyPatch, offset: tuple[int, int] | None, draw_labels: bool
) -> None:
    """真实 OpenCV 像素比较覆盖缺省、正负偏移、裁剪及关闭文字。"""

    source = np.zeros((120, 180, 3), dtype=np.uint8)
    items = [
        {"region_id": "a", "class_name": "OK", "score": 0.99, "area": 900,
         "bbox_xyxy": [40, 40, 70, 70], "polygon_xy": [[40, 40], [70, 40], [70, 70]]},
        {"region_id": "b", "class_name": "OK", "score": 0.99, "area": 900,
         "bbox_xyxy": [95, 2, 125, 32], "polygon_xy": [[95, 2], [125, 2], [125, 32]]},
    ]
    parameters = {"draw_masks": False, "draw_polygons": False, "draw_labels": draw_labels,
                  "draw_region_id": False, "draw_score": False,
                  "color_by": "class-name", "class_colors": {"OK": "#00FF00"}}
    if offset is not None:
        parameters.update(label_offset_x=offset[0], label_offset_y=offset[1])
    # 只替换图片存取，保留真实参数校验、regions 校验和 OpenCV 绘制。
    monkeypatch.setattr(draw_regions, "load_image_matrix", lambda request: ({}, None, source))
    monkeypatch.setattr(draw_regions, "encode_png_image_bytes", lambda request, **kwargs: kwargs["image_matrix"])
    monkeypatch.setattr(draw_regions, "build_output_image_payload", lambda request, **kwargs: kwargs["content"])
    result = draw_regions.handle_node(SimpleNamespace(
        node_id="draw", parameters=parameters, input_values={"regions": {"items": items}}
    ))["image"]
    expected = source.copy()
    # 固定基线来自旧实现，覆盖靠近顶边时原有的 14 px 基线规则。
    for start, end, baseline in [((40, 40), (70, 70), (40, 34)), ((95, 2), (125, 32), (95, 14))]:
        cv2.rectangle(expected, start, end, (0, 255, 0), 2)
        if draw_labels and offset != (2147483647, 0):
            dx, dy = offset or (0, 0)
            cv2.putText(expected, "OK", (baseline[0] + dx, baseline[1] + dy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
    np.testing.assert_array_equal(result, expected)
    assert not np.any(source)
