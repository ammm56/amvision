from __future__ import annotations

import pytest

from backend.service.application.models.yolo_core_common.geometry import (
    build_yolo_letterbox_transform,
    scale_yolo_box_from_letterbox,
    scale_yolo_box_to_letterbox,
    scale_yolo_point_from_letterbox,
    scale_yolo_xywh_from_letterbox,
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
    assert transform.pad_top == 140
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
    assert transform.pad_top == 0
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
