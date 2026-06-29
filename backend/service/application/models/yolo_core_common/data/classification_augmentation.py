"""普通 YOLO classification 图像级数据增强。"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class YoloClassificationAugmentationOptions:
    """描述普通 YOLO classification 训练时使用的图像级增强参数。"""

    flip_prob: float = 0.5
    hsv_prob: float = 1.0
    random_erasing_prob: float = 0.0


def build_yolo_classification_augmentation_options(
    extra_options: dict[str, object] | None,
) -> YoloClassificationAugmentationOptions:
    """从训练 extra_options 构造 classification 图像级增强参数。"""

    extra = dict(extra_options or {})
    if _read_bool_option(
        extra,
        "disable_augmentation",
        extra.get("no_augmentation", extra.get("no_aug", False)),
    ):
        return YoloClassificationAugmentationOptions(
            flip_prob=0.0,
            hsv_prob=0.0,
            random_erasing_prob=0.0,
        )

    return YoloClassificationAugmentationOptions(
        flip_prob=_clamp_probability(
            _read_float_option(extra, "flip_prob", default=0.5)
        ),
        hsv_prob=_clamp_probability(_read_float_option(extra, "hsv_prob", default=1.0)),
        random_erasing_prob=_clamp_probability(
            _read_float_option(extra, "random_erasing_prob", default=0.0)
        ),
    )


def apply_yolo_classification_augmentation(
    *,
    image: Any,
    options: YoloClassificationAugmentationOptions | None,
    cv2_module: Any,
    np_module: Any,
) -> Any:
    """对 classification 训练图片执行图像级增强。"""

    if options is None:
        return image

    augmented = image
    if options.flip_prob > 0.0 and random.random() < options.flip_prob:
        augmented = augmented[:, ::-1].copy()
    augmented = _apply_random_hsv(
        image=augmented,
        hsv_prob=options.hsv_prob,
        cv2_module=cv2_module,
        np_module=np_module,
    )
    augmented = _apply_random_erasing(
        image=augmented,
        erasing_prob=options.random_erasing_prob,
        np_module=np_module,
    )
    return augmented


def _apply_random_hsv(
    *,
    image: Any,
    hsv_prob: float,
    cv2_module: Any,
    np_module: Any,
) -> Any:
    """按普通 YOLO 训练习惯做轻量 HSV 抖动。"""

    if hsv_prob <= 0.0 or random.random() >= hsv_prob:
        return image

    hue_gain = 0.015
    saturation_gain = 0.7
    value_gain = 0.4
    gains = np_module.random.uniform(-1.0, 1.0, 3) * [
        hue_gain,
        saturation_gain,
        value_gain,
    ] + 1.0
    hue, saturation, value = cv2_module.split(
        cv2_module.cvtColor(image, cv2_module.COLOR_BGR2HSV)
    )
    dtype = image.dtype
    lut_hue = ((np_module.arange(0, 256, dtype=gains.dtype) * gains[0]) % 180).astype(dtype)
    lut_sat = np_module.clip(
        np_module.arange(0, 256, dtype=gains.dtype) * gains[1],
        0,
        255,
    ).astype(dtype)
    lut_val = np_module.clip(
        np_module.arange(0, 256, dtype=gains.dtype) * gains[2],
        0,
        255,
    ).astype(dtype)
    hsv = cv2_module.merge(
        (
            cv2_module.LUT(hue, lut_hue),
            cv2_module.LUT(saturation, lut_sat),
            cv2_module.LUT(value, lut_val),
        )
    )
    return cv2_module.cvtColor(hsv, cv2_module.COLOR_HSV2BGR)


def _apply_random_erasing(
    *,
    image: Any,
    erasing_prob: float,
    np_module: Any,
) -> Any:
    """执行 classification 常用的随机擦除增强。"""

    if erasing_prob <= 0.0 or random.random() >= erasing_prob:
        return image

    height, width = image.shape[:2]
    if height <= 2 or width <= 2:
        return image
    area = height * width
    erase_area = random.uniform(0.02, 0.2) * area
    aspect = random.uniform(0.3, 3.3)
    erase_height = max(1, min(height, int(round((erase_area * aspect) ** 0.5))))
    erase_width = max(1, min(width, int(round((erase_area / aspect) ** 0.5))))
    top = random.randint(0, max(0, height - erase_height))
    left = random.randint(0, max(0, width - erase_width))
    fill_value = np_module.array([114, 114, 114], dtype=image.dtype)
    erased = image.copy()
    erased[top : top + erase_height, left : left + erase_width] = fill_value
    return erased


def _read_float_option(
    extra: dict[str, object],
    key: str,
    *,
    default: float,
) -> float:
    """读取浮点配置。"""

    value = extra.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_bool_option(
    extra: dict[str, object],
    key: str,
    default: object,
) -> bool:
    """读取布尔配置。"""

    value = extra.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _clamp_probability(value: float) -> float:
    """把概率限制到 0 到 1。"""

    return max(0.0, min(1.0, float(value)))


__all__ = [
    "YoloClassificationAugmentationOptions",
    "apply_yolo_classification_augmentation",
    "build_yolo_classification_augmentation_options",
]
