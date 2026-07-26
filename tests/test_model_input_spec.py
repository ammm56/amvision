from __future__ import annotations

import cv2
import numpy as np
import pytest

from backend.service.application.models.yolo_core_common.data import (
    prepare_yolo_classification_image,
)
from backend.service.application.models.yolo_core_common.geometry import (
    letterbox_yolo_image,
)
from backend.service.domain.models.model_input_spec import (
    ModelInputSpec,
    SpatialSize,
    build_yolo_model_input_spec,
)


def test_spatial_size_exposes_explicit_hw_and_wh_orders() -> None:
    size = SpatialSize(width=640, height=384)

    assert size.to_payload() == {"width": 640, "height": 384}
    assert size.hw == (384, 640)
    assert size.wh == (640, 384)


def test_spatial_size_rejects_ambiguous_sequence_payload() -> None:
    with pytest.raises(ValueError, match="width 和 height"):
        SpatialSize.from_payload([640, 384])


@pytest.mark.parametrize(
    ("model_type", "task_type", "preprocess", "normalization"),
    [
        (model_type, task_type, preprocess, normalization)
        for model_type in ("yolov8", "yolo11", "yolo26")
        for task_type, preprocess, normalization in (
            ("detection", "letterbox", "zero-to-one"),
            ("segmentation", "letterbox", "zero-to-one"),
            ("pose", "letterbox", "zero-to-one"),
            ("obb", "letterbox", "zero-to-one"),
            ("classification", "resize-center-crop", "imagenet"),
        )
    ],
)
def test_yolo_model_input_spec_matches_task_contract(
    model_type: str,
    task_type: str,
    preprocess: str,
    normalization: str,
) -> None:
    spec = build_yolo_model_input_spec(
        spatial_size=SpatialSize(width=640, height=384),
        task_type=task_type,
    )

    assert spec.tensor_shape == (1, 3, 384, 640)
    assert spec.preprocess == preprocess
    assert spec.normalization == normalization
    assert model_type in {"yolov8", "yolo11", "yolo26"}
    assert ModelInputSpec.from_payload(spec.to_payload()) == spec


@pytest.mark.parametrize(
    ("model_type", "task_type"),
    [
        (model_type, task_type)
        for model_type in ("yolov8", "yolo11", "yolo26")
        for task_type in (
            "detection",
            "classification",
            "segmentation",
            "pose",
            "obb",
        )
    ],
)
def test_three_yolo_generations_share_non_square_image_contract(
    model_type: str,
    task_type: str,
) -> None:
    """三代五任务均把公开 width/height 转为正确的 HWC/CHW 空间顺序。"""

    source_image = np.zeros((100, 320, 3), dtype=np.uint8)
    size = SpatialSize(width=160, height=96)
    spec = build_yolo_model_input_spec(spatial_size=size, task_type=task_type)

    if task_type == "classification":
        prepared = prepare_yolo_classification_image(
            image=source_image,
            input_size=size.hw,
            training=False,
            cv2_module=cv2,
        )
        assert prepared.shape == (96, 160, 3)
    else:
        prepared, transform = letterbox_yolo_image(
            cv2_module=cv2,
            np_module=np,
            image=source_image,
            input_size=size.hw,
            scaleup=False,
        )
        assert prepared.shape == (96, 160, 3)
        assert transform.target_size == (96, 160)
        assert transform.resized_width == 160
        assert transform.resized_height == 50
        assert transform.pad_top + transform.pad_bottom == 46

    assert spec.tensor_shape == (1, 3, 96, 160)
    assert model_type in {"yolov8", "yolo11", "yolo26"}


def test_model_input_spec_rejects_tensor_shape_mismatch() -> None:
    spec = build_yolo_model_input_spec(
        spatial_size=SpatialSize(width=640, height=384),
        task_type="detection",
    )
    payload = spec.to_payload()
    payload["tensor_shape"] = [1, 3, 640, 384]

    with pytest.raises(ValueError, match="tensor_shape"):
        ModelInputSpec.from_payload(payload)
