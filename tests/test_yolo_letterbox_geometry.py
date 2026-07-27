from __future__ import annotations

import cv2
import numpy as np
import pytest

from backend.service.application.models.yolo_core_common.geometry import (
    build_yolo_letterbox_transform,
    scale_yolo_box_from_letterbox,
    scale_yolo_box_to_letterbox,
    scale_yolo_mask_from_letterbox,
    scale_yolo_mask_to_letterbox,
    scale_yolo_point_from_letterbox,
    scale_yolo_point_to_letterbox,
    scale_yolo_xywh_from_letterbox,
    scale_yolo_xywhr_from_letterbox,
    scale_yolo_xywhr_to_letterbox,
)


def test_yolo_letterbox_transform_matches_wide_image_padding() -> None:
    transform = build_yolo_letterbox_transform(
        source_width=1280,
        source_height=720,
        input_size=(640, 640),
    )

    assert transform.gain == pytest.approx(0.5)
    assert transform.resized_width == 640
    assert transform.resized_height == 360
    assert transform.pad_left == 0
    assert transform.pad_right == 0
    assert transform.pad_top == 140
    assert transform.pad_bottom == 140
    assert transform.target_size == (640, 640)
    assert transform.source_size == (720, 1280)


def test_yolo_letterbox_transform_matches_tall_image_padding() -> None:
    transform = build_yolo_letterbox_transform(
        source_width=720,
        source_height=1280,
        input_size=(640, 640),
    )

    assert transform.gain == pytest.approx(0.5)
    assert transform.resized_width == 360
    assert transform.resized_height == 640
    assert transform.pad_left == 140
    assert transform.pad_right == 140
    assert transform.pad_top == 0
    assert transform.pad_bottom == 0
    assert transform.target_size == (640, 640)
    assert transform.source_size == (1280, 720)


def test_yolo_letterbox_box_roundtrip_preserves_source_coordinates() -> None:
    transform = build_yolo_letterbox_transform(
        source_width=1920,
        source_height=1080,
        input_size=(640, 640),
    )
    source_box = (120.0, 80.0, 900.0, 600.0)

    letterbox_box = scale_yolo_box_to_letterbox(
        box_xyxy=source_box,
        transform=transform,
    )
    assert letterbox_box is not None
    restored_box = scale_yolo_box_from_letterbox(
        box_xyxy=letterbox_box,
        transform=transform,
    )

    assert restored_box is not None
    assert restored_box == pytest.approx(source_box)


def test_yolo_letterbox_point_and_xywh_roundtrip_use_width_height_order() -> None:
    transform = build_yolo_letterbox_transform(
        source_width=1920,
        source_height=1080,
        input_size=(640, 640),
    )

    point = scale_yolo_point_from_letterbox(
        point_xy=(
            640.0 * (960.0 / 1920.0),
            140.0 + 360.0 * (540.0 / 1080.0),
        ),
        transform=transform,
    )
    box_xywh = scale_yolo_xywh_from_letterbox(
        box_xywh=(320.0, 320.0, 160.0, 80.0),
        transform=transform,
    )

    assert point == pytest.approx((960.0, 540.0))
    assert box_xywh is not None
    assert box_xywh == pytest.approx((960.0, 540.0, 480.0, 240.0))


def test_yolo_letterbox_validation_does_not_scale_up_small_image() -> None:
    transform = build_yolo_letterbox_transform(
        source_width=200,
        source_height=100,
        input_size=(384, 640),
        scaleup=False,
    )

    assert transform.gain == pytest.approx(1.0)
    assert transform.resized_width == 200
    assert transform.resized_height == 100
    assert transform.pad_left == 220
    assert transform.pad_right == 220
    assert transform.pad_top == 142
    assert transform.pad_bottom == 142
    assert transform.target_size == (384, 640)


def test_yolo_letterbox_auto_uses_stride_aligned_dynamic_canvas() -> None:
    transform = build_yolo_letterbox_transform(
        source_width=500,
        source_height=300,
        input_size=(640, 640),
        auto=True,
        stride=32,
    )

    assert transform.target_height % 32 == 0
    assert transform.target_width % 32 == 0
    assert transform.resized_height + transform.pad_top + transform.pad_bottom == (
        transform.target_height
    )
    assert transform.resized_width + transform.pad_left + transform.pad_right == (
        transform.target_width
    )


def test_yolo_letterbox_odd_padding_matches_reference_rounding() -> None:
    """奇数 padding 必须由 -0.1/+0.1 规则稳定分配到两侧。"""

    transform = build_yolo_letterbox_transform(
        source_width=320,
        source_height=100,
        input_size=(97, 161),
    )

    assert transform.target_size == (97, 161)
    assert transform.resized_width == 161
    assert transform.resized_height == 50
    assert transform.pad_left == 0
    assert transform.pad_right == 0
    assert transform.pad_top == 23
    assert transform.pad_bottom == 24
    assert transform.resized_height + transform.pad_top + transform.pad_bottom == 97


def test_yolo_non_square_keypoint_and_obb_roundtrip() -> None:
    """keypoint 与 OBB 在非方形画布上的正反变换共享同一 transform。"""

    transform = build_yolo_letterbox_transform(
        source_width=853,
        source_height=347,
        input_size=(384, 640),
    )
    source_point = (741.25, 123.5)
    mapped_point = scale_yolo_point_to_letterbox(
        point_xy=source_point,
        transform=transform,
    )
    restored_point = scale_yolo_point_from_letterbox(
        point_xy=mapped_point,
        transform=transform,
    )
    source_obb = (421.5, 190.25, 170.0, 42.5, -0.37)
    mapped_obb = scale_yolo_xywhr_to_letterbox(
        box_xywhr=source_obb,
        transform=transform,
    )
    assert mapped_obb is not None
    restored_obb = scale_yolo_xywhr_from_letterbox(
        box_xywhr=mapped_obb,
        transform=transform,
    )

    assert restored_point == pytest.approx(source_point)
    assert restored_obb is not None
    assert restored_obb == pytest.approx(source_obb)


def test_yolo_non_square_mask_roundtrip_preserves_region() -> None:
    """mask 正反变换必须正确移除非方形 LetterBox 的奇数 padding。"""

    transform = build_yolo_letterbox_transform(
        source_width=317,
        source_height=113,
        input_size=(193, 321),
    )
    source_mask = np.zeros((113, 317), dtype=np.uint8)
    source_mask[17:91, 43:271] = 1
    mapped_mask = scale_yolo_mask_to_letterbox(
        mask=source_mask,
        transform=transform,
        cv2_module=cv2,
        np_module=np,
    )
    restored_mask = scale_yolo_mask_from_letterbox(
        mask=mapped_mask,
        transform=transform,
        cv2_module=cv2,
        np_module=np,
    )
    intersection = np.logical_and(source_mask, restored_mask).sum()
    union = np.logical_or(source_mask, restored_mask).sum()

    assert mapped_mask.shape == (193, 321)
    assert restored_mask.shape == source_mask.shape
    # 两次 nearest resize 允许轮廓产生一个像素的量化边界，不允许 padding 漂移。
    assert float(intersection) / float(union) > 0.96
