from __future__ import annotations

import math
import random
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from backend.service.application.models.yolo_core_common.data import (
    classification_augmentation,
)
from backend.service.application.models.yolo_core_common.data import (
    prepare_yolo_classification_image,
)
from backend.service.application.models.yolo_core_common.geometry import (
    letterbox_yolo_image,
)
from backend.service.application.models.registry.model_service import (
    SqlAlchemyModelService,
)
from backend.service.domain.models.model_input_spec import (
    ModelInputSpec,
    SpatialSize,
    build_platform_model_input_spec,
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


@pytest.mark.parametrize(
    ("model_type", "preprocess", "normalization", "center", "postprocess"),
    [
        ("yolox", "yolox-top-left-letterbox", "none", False, "yolox-detection-v1"),
        ("rfdetr", "resize", "imagenet", False, "rfdetr-detection-v1"),
    ],
)
def test_platform_model_input_spec_covers_yolox_and_rfdetr(
    model_type: str,
    preprocess: str,
    normalization: str,
    center: bool,
    postprocess: str,
) -> None:
    """非 YOLO 主线模型同样持久化无宽高歧义的完整输入契约。"""

    spec = build_platform_model_input_spec(
        model_type=model_type,
        spatial_size=SpatialSize(width=672, height=416),
        task_type="detection",
    )

    assert spec.tensor_shape == (1, 3, 416, 672)
    assert spec.preprocess == preprocess
    assert spec.normalization == normalization
    assert spec.center is center
    assert spec.postprocess_contract == postprocess
    assert ModelInputSpec.from_payload(spec.to_payload()) == spec


@pytest.mark.parametrize(
    ("model_type", "task_type", "model_scale", "expected"),
    [
        ("yolox", "detection", "nano", {"width": 640, "height": 640}),
        ("rfdetr", "detection", "nano", {"width": 384, "height": 384}),
        ("rfdetr", "segmentation", "nano", {"width": 312, "height": 312}),
    ],
)
def test_pretrained_registration_uses_model_native_default_input_size(
    model_type: str,
    task_type: str,
    model_scale: str,
    expected: dict[str, int],
) -> None:
    """预训练登记不得把 YOLO 主线默认尺寸误套到 YOLOX/RF-DETR。"""

    service = object.__new__(SqlAlchemyModelService)
    service.spec = SimpleNamespace(model_name=model_type)

    spatial_size = service._resolve_default_model_input_size(
        task_type=task_type,
        model_scale=model_scale,
    )

    assert spatial_size.to_payload() == expected


def test_random_resized_crop_matches_sampled_numeric_crop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """固定采样时，RandomResizedCrop 的 crop 尺寸、位置和 resize 数值可复算。"""

    image = np.arange(100 * 150 * 3, dtype=np.uint32).reshape(100, 150, 3)
    image = (image % 251).astype(np.uint8)

    def fake_uniform(left: float, right: float) -> float:
        if left == pytest.approx(0.5) and right == pytest.approx(1.0):
            return 0.5
        return 0.0

    monkeypatch.setattr(classification_augmentation.random, "uniform", fake_uniform)
    monkeypatch.setattr(
        classification_augmentation.random,
        "randint",
        lambda _left, _right: 3,
    )
    result = prepare_yolo_classification_image(
        image=image,
        input_size=(48, 80),
        training=True,
        cv2_module=cv2,
    )
    crop_size = int(round(math.sqrt(0.5 * 100.0 * 150.0)))
    expected = cv2.resize(
        image[3 : 3 + crop_size, 3 : 3 + crop_size],
        (80, 48),
        interpolation=cv2.INTER_LINEAR,
    )

    assert np.array_equal(result, expected)


def test_random_resized_crop_fallback_matches_reference_ratio_crop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """连续采样失败时必须使用 RandomResizedCrop 的 ratio 边界中心裁剪。"""

    image = np.arange(50 * 300 * 3, dtype=np.uint32).reshape(50, 300, 3)
    image = (image % 251).astype(np.uint8)
    monkeypatch.setattr(
        classification_augmentation.random,
        "uniform",
        lambda left, right: right,
    )

    result = prepare_yolo_classification_image(
        image=image,
        input_size=(40, 80),
        training=True,
        cv2_module=cv2,
    )

    expected_crop_width = int(round(50.0 * (4.0 / 3.0)))
    expected_left = (300 - expected_crop_width) // 2
    expected_crop = image[:, expected_left : expected_left + expected_crop_width]
    expected = cv2.resize(expected_crop, (80, 40), interpolation=cv2.INTER_LINEAR)
    assert np.array_equal(result, expected)


def test_random_resized_crop_is_seeded_random_but_validation_is_deterministic() -> None:
    """训练 crop 响应随机种子，validation 中心裁剪不受随机状态影响。"""

    yy, xx = np.mgrid[:120, :200]
    image = np.stack((xx % 256, yy % 256, (xx + yy) % 256), axis=-1).astype(np.uint8)
    random.seed(17)
    training_a = prepare_yolo_classification_image(
        image=image,
        input_size=(64, 96),
        training=True,
        cv2_module=cv2,
    )
    random.seed(17)
    training_b = prepare_yolo_classification_image(
        image=image,
        input_size=(64, 96),
        training=True,
        cv2_module=cv2,
    )
    random.seed(18)
    training_c = prepare_yolo_classification_image(
        image=image,
        input_size=(64, 96),
        training=True,
        cv2_module=cv2,
    )
    random.seed(101)
    validation_a = prepare_yolo_classification_image(
        image=image,
        input_size=(64, 96),
        training=False,
        cv2_module=cv2,
    )
    random.seed(202)
    validation_b = prepare_yolo_classification_image(
        image=image,
        input_size=(64, 96),
        training=False,
        cv2_module=cv2,
    )

    assert np.array_equal(training_a, training_b)
    assert not np.array_equal(training_a, training_c)
    assert np.array_equal(validation_a, validation_b)
