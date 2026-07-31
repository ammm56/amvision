"""普通 YOLO classification 通用数据增强测试。"""

from __future__ import annotations

import random

import cv2
import numpy as np
import pytest

from backend.service.application.models.yolo_core_common.data import (
    apply_yolo_classification_augmentation,
    build_yolo_classification_augmentation_options,
    build_yolo_classification_augmentation_summary,
    prepare_yolo_classification_image,
)


def test_build_manual_classification_augmentation_options() -> None:
    """关闭自动策略后，手动增强参数应完整解析。"""

    options = build_yolo_classification_augmentation_options(
        {
            "flip_prob": 0.25,
            "crop_mode": "random_resized_crop",
            "crop_scale_min": 0.7,
            "crop_scale_max": 0.9,
            "auto_augment": "none",
            "rotation_degrees": 4,
            "translate_ratio": 0.05,
            "scale_min": 0.95,
            "scale_max": 1.05,
            "brightness_gain": 0.1,
            "contrast_gain": 0.2,
            "gamma_min": 0.9,
            "gamma_max": 1.1,
            "hue_gain": 0.01,
            "saturation_gain": 0.15,
            "value_gain": 0.12,
            "random_erasing_prob": 0.1,
        }
    )

    assert options.auto_augment is None
    assert options.crop_scale_min == pytest.approx(0.7)
    assert options.crop_scale_max == pytest.approx(0.9)
    assert options.rotation_degrees == pytest.approx(4.0)
    assert options.gamma_max == pytest.approx(1.1)
    assert build_yolo_classification_augmentation_summary(options)[
        "auto_augment"
    ] == "none"


def test_auto_augment_normalizes_manual_parameters_to_noop() -> None:
    """自动增强启用时不得继续叠加手动仿射和颜色增强。"""

    options = build_yolo_classification_augmentation_options(
        {
            "auto_augment": "augmix",
            "rotation_degrees": 30,
            "brightness_gain": 0.5,
            "gamma_min": 0.5,
            "gamma_max": 1.5,
        }
    )

    assert options.auto_augment == "augmix"
    assert options.rotation_degrees == 0.0
    assert options.brightness_gain == 0.0
    assert options.gamma_min == 1.0
    assert options.gamma_max == 1.0


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"flip_prob": 1.1}, "flip_prob"),
        ({"crop_scale_min": 0.05}, "crop_scale_min"),
        (
            {"crop_scale_min": 0.9, "crop_scale_max": 0.5},
            "crop_scale_min",
        ),
        (
            {"auto_augment": "none", "scale_min": 1.2, "scale_max": 0.8},
            "scale_min",
        ),
        (
            {"auto_augment": "none", "gamma_min": 1.2, "gamma_max": 0.8},
            "gamma_min",
        ),
        ({"auto_augment": "none", "translate_ratio": 0.51}, "translate_ratio"),
        ({"auto_augment": "none", "scale_max": 2.01}, "scale_max"),
        ({"auto_augment": "none", "gamma_max": 5.01}, "gamma_max"),
        ({"crop_mode": "fixed_roi"}, "crop_mode"),
    ],
)
def test_invalid_classification_augmentation_options_are_rejected(
    payload: dict[str, object],
    message: str,
) -> None:
    """非法范围和业务型 crop 配置不得被静默钳制。"""

    with pytest.raises(ValueError, match=message):
        build_yolo_classification_augmentation_options(payload)


def test_disable_augmentation_resolves_to_deterministic_noop_summary() -> None:
    """关闭增强必须覆盖所有随机参数。"""

    options = build_yolo_classification_augmentation_options(
        {
            "disable_augmentation": True,
            "auto_augment": "augmix",
            "flip_prob": 1,
        }
    )
    summary = build_yolo_classification_augmentation_summary(options)

    assert summary["disable_augmentation"] is True
    assert summary["crop_mode"] == "none"
    assert summary["crop_scale_min"] == 1.0
    assert summary["auto_augment"] == "none"
    assert summary["flip_prob"] == 0.0
    assert summary["random_erasing_prob"] == 0.0


def test_manual_crop_and_affine_use_one_resampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """随机 crop 与手动 affine 必须合并到单次 warpAffine。"""

    image = np.arange(80 * 120 * 3, dtype=np.uint32).reshape(80, 120, 3)
    image = (image % 251).astype(np.uint8)
    options = build_yolo_classification_augmentation_options(
        {
            "crop_mode": "random_resized_crop",
            "crop_scale_min": 0.8,
            "crop_scale_max": 0.8,
            "auto_augment": "none",
            "rotation_degrees": 3,
        }
    )
    calls = {"warp": 0}
    original_warp = cv2.warpAffine

    def tracked_warp(*args: object, **kwargs: object) -> np.ndarray:
        calls["warp"] += 1
        return original_warp(*args, **kwargs)

    monkeypatch.setattr(cv2, "warpAffine", tracked_warp)
    random.seed(11)
    result = prepare_yolo_classification_image(
        image=image,
        input_size=(48, 64),
        training=True,
        cv2_module=cv2,
        augmentation_options=options,
    )

    assert result.shape == (48, 64, 3)
    assert calls["warp"] == 1


def test_manual_color_augmentation_changes_image_without_changing_shape() -> None:
    """手动颜色链路应保持图像布局并产生可见变化。"""

    image = np.full((24, 32, 3), 96, dtype=np.uint8)
    options = build_yolo_classification_augmentation_options(
        {
            "auto_augment": "none",
            "brightness_gain": 0.2,
            "contrast_gain": 0.2,
            "gamma_min": 0.8,
            "gamma_max": 0.8,
            "hue_gain": 0.02,
            "saturation_gain": 0.2,
            "value_gain": 0.2,
        }
    )
    np.random.seed(7)
    result = apply_yolo_classification_augmentation(
        image=image,
        options=options,
        cv2_module=cv2,
        np_module=np,
    )

    assert result.shape == image.shape
    assert result.dtype == np.uint8
    assert not np.array_equal(result, image)
